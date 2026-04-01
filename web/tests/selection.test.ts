import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Selection", () => {
  test("record detail overlay opens on thumbnail click", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });

    const firstCard = panel.getByTestId("source-record-card").first();
    const thumb = firstCard.locator("img").first();
    if (await thumb.isVisible({ timeout: 2000 }).catch(() => false)) {
      await thumb.click();
    } else {
      await firstCard.getByText("OCR").click();
    }

    const detail = page.getByTestId("record-detail");
    await expect(detail).toBeVisible({ timeout: 5000 });

    await page.getByTestId("record-detail-close").click();
    await expect(detail).not.toBeVisible();
  });

  test("selection bar appears when right-clicking records", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    const cards = panel.getByTestId("source-record-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    await cards.first().click({ button: "right" });

    const selCount = page.getByTestId("selection-count");
    await expect(selCount.first()).toBeVisible({ timeout: 5000 });
    await expect(selCount.first()).toContainText("1 selected");

    await page.getByTestId("selection-cancel").first().click();
    await expect(selCount.first()).not.toBeVisible();

    await expect(cards.first()).toBeVisible();
  });

  test("Selection bar shows delete button when records selected", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    const cards = panel.getByTestId("source-record-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    await cards.first().click({ button: "right" });

    await expect(page.getByTestId("selection-count").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId("selection-delete").first()).toBeVisible();

    await page.getByTestId("selection-cancel").first().click();
    await expect(page.getByTestId("selection-count").first()).not.toBeVisible();
  });
});
