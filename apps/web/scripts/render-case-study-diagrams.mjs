import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "@playwright/test";

const webRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repositoryRoot = path.resolve(webRoot, "../..");
const sourceDirectory = path.join(repositoryRoot, "docs/case-study/diagrams");
const outputDirectory = path.join(sourceDirectory, "generated");
const configuration = path.join(
  repositoryRoot,
  "docs/case-study/mermaid-theme.json",
);
const puppeteerConfiguration = path.join(
  repositoryRoot,
  "docs/case-study/puppeteer-config.json",
);

mkdirSync(outputDirectory, { recursive: true });
for (const source of readdirSync(sourceDirectory)
  .filter((name) => name.endsWith(".mmd"))
  .sort()) {
  const output = path.join(outputDirectory, source.replace(/\.mmd$/, ".svg"));
  execFileSync(
    "pnpm",
    [
      "exec",
      "mmdc",
      "--quiet",
      "--backgroundColor",
      "transparent",
      "--configFile",
      configuration,
      "--puppeteerConfigFile",
      puppeteerConfiguration,
      "--input",
      path.join(sourceDirectory, source),
      "--output",
      output,
    ],
    {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        PUPPETEER_EXECUTABLE_PATH: chromium.executablePath(),
      },
      stdio: "inherit",
    },
  );
}
