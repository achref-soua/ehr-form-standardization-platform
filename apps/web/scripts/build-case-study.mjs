import { existsSync, mkdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

import { chromium } from "@playwright/test";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repositoryRoot = path.resolve(webRoot, "../..");
const source = path.join(repositoryRoot, "docs/case-study/case-study.fr.html");
const destination = path.join(
  repositoryRoot,
  "docs/case-study/epiconcept-case-study.fr.pdf",
);

if (!existsSync(source))
  throw new Error(`Missing case-study source: ${source}`);
mkdirSync(path.dirname(destination), { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1100 },
  });
  await page.goto(pathToFileURL(source).href, { waitUntil: "networkidle" });
  const layout = await page.locator(".page").evaluateAll((pages) =>
    pages.map((item, index) => ({
      page: index + 1,
      horizontalOverflow: item.scrollWidth - item.clientWidth,
      verticalOverflow: item.scrollHeight - item.clientHeight,
    })),
  );
  if (layout.length !== 8)
    throw new Error(`Expected 8 HTML pages, found ${layout.length}`);
  const overflowing = layout.filter(
    ({ horizontalOverflow, verticalOverflow }) =>
      horizontalOverflow > 1 || verticalOverflow > 1,
  );
  if (overflowing.length > 0)
    throw new Error(`Case-study overflow: ${JSON.stringify(overflowing)}`);
  await page.pdf({
    path: destination,
    format: "A4",
    landscape: true,
    printBackground: true,
    preferCSSPageSize: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
    displayHeaderFooter: false,
    tagged: true,
  });
} finally {
  await browser.close();
}
