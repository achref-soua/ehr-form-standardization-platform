import { expect, test } from "@playwright/test";

const routes = [
  ["/", "command-center"],
  ["/sources", "source-explorer"],
  ["/forms", "form-registry"],
  ["/mappings", "mapping-workspace"],
  ["/runs", "pipeline-runs"],
  ["/quarantine", "quarantine"],
  ["/documents", "document-lab"],
  ["/omop", "omop-explorer"],
  ["/catalog", "research-catalog"],
  ["/lineage", "lineage"],
  ["/health", "system-health"],
] as const;

for (const [route, slug] of routes) {
  test(`${slug} screenshot has no horizontal viewport overflow`, async ({
    page,
  }, testInfo) => {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );
    if (slug === "system-health") {
      await page.getByTestId("health-check-time").evaluate((element) => {
        element.textContent = "Checked 12:00:00";
      });
    }
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflows).toBe(false);
    await page.screenshot({
      path: `../../docs/assets/generated/${slug}-${testInfo.project.name}.png`,
      fullPage: false,
      animations: "disabled",
    });
  });
}
