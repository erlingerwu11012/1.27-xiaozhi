// Render every page in source/pages/ to a full-resolution PNG.
//
//   node source/scripts/render.mjs            # all pages
//   node source/scripts/render.mjs 03 07a     # only pages whose filename starts with these prefixes
//
// Output: exports/pages/<page-name>.png (1440px wide, height follows content).
// Also runs basic QA: fonts loaded, images decoded, no overflowing text boxes.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const pagesDir = path.join(root, "source/pages");
const outDir = path.join(root, "exports/pages");
fs.mkdirSync(outDir, { recursive: true });

const filters = process.argv.slice(2);
const files = fs
  .readdirSync(pagesDir)
  .filter((f) => f.endsWith(".html"))
  .filter((f) => !filters.length || filters.some((p) => f.startsWith(p)))
  .sort();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 }, deviceScaleFactor: 1 });
let problems = 0;

for (const file of files) {
  await page.goto(pathToFileURL(path.join(pagesDir, file)).href, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);

  const qa = await page.evaluate(() => {
    const issues = [];
    for (const f of document.fonts) if (f.status !== "loaded" && f.status !== "unloaded") issues.push(`font ${f.family} ${f.weight}: ${f.status}`);
    for (const f of document.fonts) if (f.status === "error") issues.push(`font failed: ${f.family} ${f.weight}`);
    for (const img of document.images) if (!img.complete || img.naturalWidth === 0) issues.push(`broken image: ${img.src}`);
    for (const el of document.querySelectorAll(".page *")) {
      if (el.children.length) continue;
      const cs = getComputedStyle(el);
      if (el.scrollWidth > el.clientWidth + 1 && cs.overflow !== "visible") issues.push(`overflow-x: ${el.className} "${el.textContent.trim().slice(0, 20)}"`);
      if (el.scrollHeight > el.clientHeight + 1 && cs.overflow !== "visible") issues.push(`overflow-y: ${el.className} "${el.textContent.trim().slice(0, 20)}"`);
    }
    const pg = document.querySelector(".page").getBoundingClientRect();
    for (const el of document.querySelectorAll(".page [data-text], .page p, .page h1, .page h2, .page h3, .page span, .page div")) {
      if (!el.textContent.trim() || el.children.length) continue;
      const r = el.getBoundingClientRect();
      if (r.width && (r.left < pg.left - 0.5 || r.right > pg.right + 0.5)) issues.push(`outside page: "${el.textContent.trim().slice(0, 20)}"`);
    }
    return { issues };
  });

  const el = await page.$(".page");
  const name = file.replace(/\.html$/, ".png");
  await el.screenshot({ path: path.join(outDir, name) });
  const box = await el.boundingBox();
  console.log(`${name}  ${Math.round(box.width)}x${Math.round(box.height)}${qa.issues.length ? "  ISSUES:\n   - " + qa.issues.join("\n   - ") : "  ok"}`);
  problems += qa.issues.length;
}

await browser.close();
if (problems) process.exitCode = 1;
