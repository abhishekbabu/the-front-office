/**
 * Screenshot every view, so the UI can be looked at rather than reasoned about.
 *
 * Starts the preview server itself and stops it after, so this is one command
 * from a clean shell. Shots land in web/.shots, which is gitignored — they are
 * a way of looking at the app, not an artifact of it.
 *
 * Usage: pnpm shoot [--dark] [--only=landing,scout]
 */
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = path.join(ROOT, "web/.shots");
const BASE = "http://127.0.0.1:8100";

const args = process.argv.slice(2);
const dark = args.includes("--dark");
const only = args.find((a) => a.startsWith("--only="))?.slice("--only=".length)?.split(",");

/** Wait for the server to answer rather than sleeping a guessed interval. */
async function waitForServer(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE}/api/sports`);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Preview server never answered on ${BASE}`);
}

async function main() {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  const server = spawn("uv", ["run", "python", "scripts/preview.py"], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const serverLog = [];
  server.stdout.on("data", (d) => serverLog.push(String(d)));
  server.stderr.on("data", (d) => serverLog.push(String(d)));

  const browser = await chromium.launch();
  try {
    await waitForServer();

    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      deviceScaleFactor: 2,
      colorScheme: dark ? "dark" : "light",
    });
    const page = await context.newPage();

    // Surface anything the app logs; a React error boundary is otherwise
    // invisible in a screenshot that just looks empty.
    const problems = [];
    page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
    page.on("pageerror", (e) => problems.push(String(e)));

    const suffix = dark ? "-dark" : "";
    const shoot = async (name) => {
      await page.waitForTimeout(350); // let queries settle
      await page.screenshot({ path: path.join(OUT, `${name}${suffix}.png`), fullPage: true });
      console.log(`  ${name}${suffix}.png`);
    };

    const wanted = (name) => !only || only.includes(name);

    await page.goto(BASE, { waitUntil: "networkidle" });
    if (wanted("landing")) await shoot("landing");

    // Into the first league of each ready sport, via the rail rather than a URL:
    // the app has no routing, so this is the only way in — and it exercises the
    // same path a person takes.
    for (const sport of ["FPL", "NFL"]) {
      const rail = page.getByRole("button", { name: sport, exact: true });
      if (!(await rail.count())) continue;
      await rail.click();
      await page.waitForTimeout(500);

      if (wanted("scout")) {
        // Explicit: switching sport keeps whichever view you were on, so after
        // the first pass this would otherwise still be showing My team.
        await page.getByRole("button", { name: "Scout", exact: true }).click();
        await page.waitForTimeout(300);
        const run = page.getByRole("button", { name: /Run (report|again)/i });
        if (await run.count()) {
          await run.click();
          await page.waitForTimeout(1200);
        }
        await shoot(`${sport.toLowerCase()}-scout`);
      }
      if (wanted("team")) {
        await page.getByRole("button", { name: "My team" }).click();
        await shoot(`${sport.toLowerCase()}-team`);
      }
      if (wanted("trade")) {
        const trade = page.getByRole("button", { name: "Trade", exact: true });
        if (await trade.count()) {
          await trade.click();
          await shoot(`${sport.toLowerCase()}-trade`);
        }
      }
    }

    if (wanted("settings")) {
      await page.getByRole("button", { name: /Settings/ }).click();
      await shoot("settings");
    }

    if (problems.length) {
      console.log("\n  Console errors:");
      for (const p of [...new Set(problems)]) console.log(`    ${p}`);
    }
  } catch (error) {
    console.error(`\n  Failed: ${error.message}`);
    console.error(serverLog.join(""));
    process.exitCode = 1;
  } finally {
    await browser.close();
    server.kill("SIGTERM");
  }
}

await main();
