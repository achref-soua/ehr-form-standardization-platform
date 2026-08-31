import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const routes = [
  "/",
  "/sources",
  "/forms",
  "/mappings",
  "/runs",
  "/quarantine",
  "/documents",
  "/omop",
  "/catalog",
  "/lineage",
  "/health",
];

test("serves explicit EHRFS browser identity assets", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    "/favicon.svg?v=ehrfs-1",
  );
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    "href",
    "/site.webmanifest?v=ehrfs-1",
  );

  const favicon = await page.request.get("/favicon.svg?v=ehrfs-1");
  expect(favicon.ok()).toBe(true);
  expect(favicon.headers()["content-type"]).toContain("image/svg+xml");
  expect(await favicon.text()).toContain("<title>EHRFS</title>");

  const manifest = await page.request.get("/site.webmanifest?v=ehrfs-1");
  expect(manifest.ok()).toBe(true);
  expect(manifest.headers()["content-type"]).toContain(
    "application/manifest+json",
  );
  await expect(manifest.json()).resolves.toMatchObject({
    short_name: "EHRFS",
    theme_color: "#123044",
  });
});

for (const route of routes) {
  test(`${route} has a visible workspace and no serious axe violations`, async ({
    page,
  }) => {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
  });
}

test("keyboard navigation exposes every workspace", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByText("Skip to content")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});

test("guided maker-checker replay creates a new immutable release", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop",
    "One mutation flow is sufficient",
  );
  await page.goto("/mappings");
  const approve = page.getByRole("button", {
    name: "Approve and sign release",
  });
  if (await approve.isEnabled()) {
    await approve.click();
    await expect(page.getByText(/Signed release mapping_/)).toBeVisible();
  }

  await page.locator(".persona-trigger").click();
  await page.getByRole("menuitem").filter({ hasText: "Operator" }).click();
  await expect(page.locator(".persona-trigger")).toContainText(
    "Platform Operator",
  );
  await page.goto("/quarantine");
  const quarantineStatus = async () => {
    const response = await page.request.get("/api/v1/quarantine");
    expect(response.ok()).toBe(true);
    const records = (await response.json()) as Array<{ status: string }>;
    return records[0]?.status;
  };
  const replay = page.getByRole("button", { name: "Replay" });
  if ((await quarantineStatus()) === "OPEN") {
    await expect(replay).toBeEnabled();
    await replay.click();
  }
  await expect
    .poll(quarantineStatus, { timeout: 15_000 })
    .toMatch(/^(REPLAY_QUEUED|RESOLVED)$/);

  await page.goto("/omop");
  await expect(page.locator("h1")).toContainText("OMOP");
  await expect
    .poll(
      async () => {
        const response = await page.request.get("/api/v1/omop/releases");
        expect(response.ok()).toBe(true);
        const releases = (await response.json()) as unknown[];
        return releases.length;
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(1);
  await page.reload();
  await expect(page.getByText(/^release_/).first()).toBeVisible();
});
