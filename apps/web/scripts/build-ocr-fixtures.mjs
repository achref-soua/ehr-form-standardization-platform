import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "@playwright/test";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const root = path.resolve(webRoot, "../..");
const output = path.join(root, "data/fixtures/ocr");
mkdirSync(path.join(output, "golden"), { recursive: true });

const documentMarkup = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>
  *{box-sizing:border-box} html,body{margin:0;background:#d9d9d9;font-family:Arial,sans-serif;color:#20233d}
  .frame{width:1120px;height:720px;margin:40px;background:white;border:4px solid #5b5bd6;padding:54px 64px;position:relative}
  .brand{color:#5b5bd6;font-size:24px;font-weight:800;letter-spacing:.08em}.tag{color:#0f766e;font-size:14px}
  h1{margin:44px 0 36px;font:42px Georgia,serif;color:#36309d}.label{font-size:17px;text-transform:uppercase;letter-spacing:.08em;color:#667085}
  .value{margin-top:12px;padding:24px;border-left:10px solid #2dd4bf;background:#ecfdf8;font-size:34px;line-height:1.35}
  .meta{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:44px;font-size:17px}.field{border-bottom:2px solid #b7bfd4;padding:10px 0}
  .signature{position:absolute;right:64px;bottom:50px;width:330px;color:#667085;font-size:14px}.signature div{margin-top:28px;border-top:2px solid #667085;padding-top:7px}
  .synthetic{position:absolute;left:64px;bottom:50px;color:#0f766e;font-weight:700;font-size:13px}
</style></head><body><article class="frame"><div class="brand">EHR FORMS <span class="tag">STANDARDIZATION PLATFORM</span></div><h1>Compte rendu d’allergologie</h1><div class="label">Antécédents allergiques</div><div class="value">Allergie à la pénicilline avec urticaire.</div><div class="meta"><div class="field">Document : SYNTH-ALL-00482</div><div class="field">Date : 12/08/2026</div></div><div class="synthetic">SPÉCIMEN SYNTHÉTIQUE — AUCUNE DONNÉE PATIENT</div><div class="signature"><div>Signature (emplacement fictif)</div></div></article></body></html>`;

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1200, height: 800 },
    deviceScaleFactor: 1,
  });
  await page.setContent(documentMarkup, { waitUntil: "load" });
  await page.screenshot({
    path: path.join(output, "allergy-clean.png"),
    type: "png",
  });
  await page.addStyleTag({
    content:
      ".frame{transform:rotate(1.4deg) scale(.965);filter:blur(.45px) contrast(.72);border-color:#557786} body{background:linear-gradient(90deg,#bcbcbc,#e0e0e0 45%,#c4c4c4)}",
  });
  await page.screenshot({
    path: path.join(output, "allergy-degraded.jpg"),
    type: "jpeg",
    quality: 46,
  });
} finally {
  await browser.close();
}

const files = ["allergy-clean.png", "allergy-degraded.jpg"];
const manifest = {
  schema_version: "1.0",
  generator: "Playwright 1.62.1 / Chromium 1234",
  synthetic: true,
  source_text: "Allergie à la pénicilline avec urticaire.",
  transformations: {
    "allergy-clean.png": [
      "native browser rasterization",
      "indigo document border",
    ],
    "allergy-degraded.jpg": [
      "rotation 1.4deg",
      "blur 0.45px",
      "contrast 72%",
      "JPEG quality 46",
      "uneven grayscale border",
    ],
  },
  files: Object.fromEntries(
    files.map((name) => [
      name,
      {
        sha256: createHash("sha256")
          .update(readFileSync(path.join(output, name)))
          .digest("hex"),
      },
    ]),
  ),
};
writeFileSync(
  path.join(output, "manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
