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

/**
 * Refuse to run against a server this script did not start.
 *
 * The spawn below cannot bind a port already in use, so it dies quietly while
 * `waitForServer` succeeds against whatever was already there — and the shots
 * come back from whatever code that process was started with. Twice now that
 * has looked exactly like a bug in the feature being photographed.
 */
async function refuseStaleServer() {
  try {
    await fetch(`${BASE}/api/sports`);
  } catch {
    return; // nothing listening, which is what we want
  }
  throw new Error(
    `Something is already serving ${BASE}. These shots would come from that process, not from your ` +
      `current code. Stop it first:\n\n  pkill -f scripts/preview.py\n`,
  );
}

async function main() {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });
  await refuseStaleServer();

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
        // Explicit: switching sport keeps whichever view you were on.
        await page.getByRole("button", { name: "This week", exact: true }).click();
        await shoot(`${sport.toLowerCase()}-week`);
      }
      if (wanted("report")) {
        const report = page.getByRole("button", { name: "Report", exact: true });
        if (await report.count()) {
          await report.click();
          const run = page.getByRole("button", { name: /Run report|Run again/i });
          if (await run.count()) {
            await run.click();
            await page.waitForTimeout(1200);
          }
          await shoot(`${sport.toLowerCase()}-report`);
        }
      }
      if (wanted("league")) {
        await page.getByRole("button", { name: "League", exact: true }).click();
        await page.waitForTimeout(2500); // a whole season of matchups
        await shoot(`${sport.toLowerCase()}-league`);
        // Each tab is a different question; one shot of the first proves
        // nothing about the others.
        for (const tab of ["Table", "Rosters", "Fixtures", "Activity"]) {
          const control = page.getByRole("tab", { name: tab });
          if (await control.count()) {
            await control.click();
            await page.waitForTimeout(400);
            await shoot(`${sport.toLowerCase()}-${tab.toLowerCase()}`);
          }
        }
      }
      if (wanted("agents")) {
        await page.getByRole("button", { name: "Free agents" }).click();
        await page.waitForTimeout(2500);
        await shoot(`${sport.toLowerCase()}-agents`);
      }
      if (wanted("team")) {
        await page.getByRole("button", { name: "My team" }).click();
        await shoot(`${sport.toLowerCase()}-team`);
      }
      if (wanted("player")) {
        // Open the first row, which is the whole point of the table being one.
        await page.getByRole("button", { name: "My team" }).click();
        await page.waitForTimeout(500);
        const row = page.locator("tbody tr").first();
        if (await row.count()) {
          await row.click();
          await page.waitForTimeout(700);
          await shoot(`${sport.toLowerCase()}-player`);
          await page.getByRole("button", { name: "Close" }).click();
        }
      }
      if (wanted("trade")) {
        const trade = page.getByRole("button", { name: "Trade", exact: true });
        if (await trade.count()) {
          await trade.click();
          await shoot(`${sport.toLowerCase()}-trade`);
        }
      }
    }

    if (wanted("scrolled")) {
      // Deliberately not fullPage: the question is what stays on screen when
      // the content moves, which a full-page capture flattens away.
      await page.getByRole("button", { name: /Settings/ }).click();
      await page.waitForTimeout(500);
      await page.mouse.move(900, 500);
      await page.mouse.wheel(0, 1400);
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(OUT, `scrolled${suffix}.png`) });
      console.log(`  scrolled${suffix}.png`);
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
