import { test, expect } from "@playwright/test";

/** Click a sidebar nav item by its data-testid */
async function nav(page: import("@playwright/test").Page, key: string) {
  await page.getByTestId(`nav-${key}`).click();
}

test.describe("Dashboard", () => {
  test("header shows engine status", async ({ page }) => {
    await page.goto("/");
    const header = page.getByTestId("header");
    await expect(header).toContainText("OBSERVER");
    await expect(page.getByTestId("engine-status")).toBeVisible();
    await expect(page.getByTestId("episode-count")).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/header.png", fullPage: false });
  });

  test("sidebar is visible with grouped navigation", async ({ page }) => {
    await page.goto("/");
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible();
    // Check category labels
    await expect(sidebar).toContainText("Capture");
    await expect(sidebar).toContainText("Memory");
    await expect(sidebar).toContainText("Usage");
    await expect(sidebar).toContainText("Logs");
  });

  test("Capture panel shows frames with pagination", async ({ page }) => {
    await page.goto("/");
    await nav(page, "frames");
    const panel = page.getByTestId("frames-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Should have frame cards (capture is running)
    const cards = panel.getByTestId("frame-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Pagination should be fixed at bottom
    const pagination = page.getByTestId("pagination");
    await expect(pagination).toBeVisible();

    // Click a frame card to select it
    await cards.first().click();

    await page.screenshot({ path: "tests/screenshots/capture.png", fullPage: true });
  });

  test("Audio panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "audio");
    const panel = page.getByTestId("audio-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/audio.png", fullPage: true });
  });

  test("Episodes panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "episodes");
    const panel = page.getByTestId("episodes-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/episodes.png", fullPage: true });
  });

  test("Playbook panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: "Run Distill" })).toBeVisible();
    await page.screenshot({ path: "tests/screenshots/playbook.png", fullPage: true });
  });

  test("Usage panel shows cost summary", async ({ page }) => {
    await page.goto("/");
    await nav(page, "usage");
    const panel = page.getByTestId("usage-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel.getByText("Total Cost")).toBeVisible();
    await expect(panel.getByText("Input Tokens")).toBeVisible();
    await expect(panel.getByText("Output Tokens")).toBeVisible();
    await expect(panel.getByText("API Calls")).toBeVisible();
    await page.screenshot({ path: "tests/screenshots/usage.png", fullPage: true });
  });

  test("OS Events panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "os-events");
    const panel = page.getByTestId("os-events-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/os-events.png", fullPage: true });
  });

  test("Logs panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "logs");
    const panel = page.getByTestId("logs-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/logs.png", fullPage: true });
  });

  test("frame detail overlay opens on thumbnail click", async ({ page }) => {
    await page.goto("/");
    await nav(page, "frames");
    const panel = page.getByTestId("frames-panel");
    await expect(panel.getByTestId("frame-card").first()).toBeVisible({ timeout: 10000 });

    // Click the thumbnail image (or OCR button) on the first card
    const firstCard = panel.getByTestId("frame-card").first();
    const thumb = firstCard.locator("img").first();
    if (await thumb.isVisible()) {
      await thumb.click();
    } else {
      // No image — click the OCR button
      await firstCard.getByText("OCR").click();
    }

    // Detail overlay should appear
    const detail = page.getByTestId("frame-detail");
    await expect(detail).toBeVisible({ timeout: 5000 });

    // Close it
    await page.getByTestId("frame-detail-close").click();
    await expect(detail).not.toBeVisible();
  });

  test("selection bar appears when selecting frames", async ({ page }) => {
    await page.goto("/");
    await nav(page, "frames");
    const panel = page.getByTestId("frames-panel");
    const cards = panel.getByTestId("frame-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Click first card to select it
    await cards.first().click();

    // Selection bar should appear with "1 selected"
    const selCount = page.getByTestId("selection-count");
    await expect(selCount.first()).toBeVisible({ timeout: 5000 });
    await expect(selCount.first()).toContainText("1 selected");

    // Click Cancel to clear selection
    await page.getByTestId("selection-cancel").first().click();
    await expect(selCount.first()).not.toBeVisible();

    // Pagination should be back
    await expect(page.getByTestId("pagination")).toBeVisible();
  });

  test("header shows capture status and toggle switch", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("engine-status")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("pipeline-toggle")).toBeVisible();
  });

  test("sidebar navigation works", async ({ page }) => {
    await page.goto("/");
    const keys = ["frames", "audio", "os-events", "episodes", "playbooks", "usage", "logs"];
    const panels = [
      "frames-panel", "audio-panel", "os-events-panel",
      "episodes-panel", "playbooks-panel", "usage-panel", "logs-panel",
    ];
    for (let i = 0; i < keys.length; i++) {
      await nav(page, keys[i]);
      await expect(page.getByTestId(panels[i])).toBeVisible({ timeout: 10000 });
    }
  });

  test("Refresh button reloads data", async ({ page }) => {
    await page.goto("/");
    await nav(page, "frames");
    const panel = page.getByTestId("frames-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Click refresh
    await panel.getByRole("button", { name: "Refresh" }).click();

    // Should still show frames after refresh
    await expect(panel.getByTestId("frame-card").first()).toBeVisible({ timeout: 10000 });
  });

  test("pagination navigates between pages", async ({ page }) => {
    await page.goto("/");
    await nav(page, "frames");
    const panel = page.getByTestId("frames-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    const pagination = page.getByTestId("pagination");
    // Only test pagination if there are multiple pages
    const nextBtn = pagination.getByRole("button", { name: "Next" });
    if (await nextBtn.isEnabled()) {
      await nextBtn.click();
      // After clicking next, Prev should be enabled
      await expect(pagination.getByRole("button", { name: "Prev" })).toBeEnabled();
      await page.screenshot({ path: "tests/screenshots/capture-page2.png", fullPage: true });
    }
  });
});
