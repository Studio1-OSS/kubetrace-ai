// Renders index.html frame by frame (deterministic timeline) to JPEGs.
//   node render.mjs                 -> all frames into frames/
//   node render.mjs preview 3 12 30 -> just those seconds into preview/
import { chromium } from "../apps/web/node_modules/@playwright/test/index.mjs";
import { mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const FPS = 30;
const here = path.dirname(new URL(import.meta.url).pathname);
const args = process.argv.slice(2);
const preview = args[0] === "preview";
const outDir = path.join(here, preview ? "preview" : "frames");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.join(here, "index.html")).href);
await page.waitForFunction(() => window.READY === true, null, { timeout: 30000 });
await page.waitForTimeout(500);
const duration = await page.evaluate(() => window.DURATION);
const times = preview ? args.slice(1).map(Number) : Array.from({ length: Math.round(duration * FPS) }, (_, i) => i / FPS);
let i = 0;
for (const t of times) {
  await page.evaluate(async (tt) => { await window.render(tt); }, t);
  const name = preview ? `t${String(t).replace(".", "_")}.jpg` : `${String(i).padStart(5, "0")}.jpg`;
  await page.screenshot({ path: path.join(outDir, name), type: "jpeg", quality: 93 });
  i++;
  if (!preview && i % 150 === 0) console.log(`${i}/${times.length}`);
}
await browser.close();
console.log(`rendered ${times.length} frames to ${outDir}`);
