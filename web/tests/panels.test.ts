import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Source Panels", () => {
  test("Screen source panel shows seeded data", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });
    const cards = panel.getByTestId("source-record-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/screen.png", fullPage: true });
  });

  test("Audio source panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:audio");
    const panel = page.getByTestId("source-panel-audio");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/audio.png", fullPage: true });
  });

  test("Zsh source panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:zsh");
    const panel = page.getByTestId("source-panel-zsh");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/zsh.png", fullPage: true });
  });

  test("Refresh button reloads data", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await panel.getByRole("button", { name: "Refresh" }).click();
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });
  });

  test("pagination works when data exceeds page size", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });
  });
});
