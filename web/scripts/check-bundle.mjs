/**
 * Fail the build when the entry bundle grows past what this app can justify.
 *
 * Everything here is loaded before anything renders, so its size is time the
 * page is blank. A budget catches the case a dependency is added for one small
 * thing and brings a library with it — which is invisible in review and shows
 * up months later as "the app got slow".
 *
 * Raise BUDGET deliberately, with the reason in the commit.
 */
import { gzipSync } from "node:zlib";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist/assets");
// 150, raised from 140 for react-router: routing is load-bearing for every
// page and belongs in the entry bundle, and the canonical library is worth its
// 10 kB over a smaller one nobody else has to learn.
const BUDGET_KB = 150;

const files = await readdir(DIST);
const entry = files.find((f) => f.startsWith("index-") && f.endsWith(".js"));
if (!entry) {
  console.error("  No entry bundle found. Did the build run?");
  process.exit(1);
}

const gzipped = gzipSync(await readFile(path.join(DIST, entry))).length / 1024;
const deferred = (
  await Promise.all(
    files
      .filter((f) => f.endsWith(".js") && f !== entry)
      .map(async (f) => gzipSync(await readFile(path.join(DIST, f))).length / 1024),
  )
).reduce((total, size) => total + size, 0);

console.log(`  entry ${gzipped.toFixed(1)} kB gzip (budget ${BUDGET_KB})`);
if (deferred) console.log(`  deferred ${deferred.toFixed(1)} kB gzip, loaded after first paint`);

if (gzipped > BUDGET_KB) {
  console.error(`\n  Over budget by ${(gzipped - BUDGET_KB).toFixed(1)} kB.`);
  console.error("  Either defer it behind a dynamic import, or raise BUDGET with the reason.");
  process.exit(1);
}
