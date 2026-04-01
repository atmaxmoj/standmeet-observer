import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Navigation", () => {
  test("header shows engine status", async ({ page }) => {
    await page.goto("/");
    const header = page.getByTestId("header");
    await expect(header).toContainText("OBSERVER");
    await expect(page.getByTestId("episode-count")).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/header.png", fullPage: false });
  });

  test("sidebar is visible with grouped navigation", async ({ page }) => {
    await page.goto("/");
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible();
    await expect(sidebar).toContainText("Sources");
    await expect(sidebar).toContainText("Memory");
    await expect(sidebar).toContainText("Usage");
    await expect(sidebar).toContainText("Logs");
  });

  test("header shows pipeline toggle switch", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("pipeline-toggle")).toBeVisible({ timeout: 10000 });
  });

  test("sidebar navigation works for all panels", async ({ page }) => {
    await page.goto("/");
    const staticPanels = [
      { key: "episodes", panel: "episodes-panel" },
      { key: "playbooks", panel: "playbooks-panel" },
      { key: "routines", panel: "routines-panel" },
      { key: "insights", panel: "insights-panel" },
      { key: "chat", panel: "chat-panel" },
      { key: "usage", panel: "usage-panel" },
      { key: "logs", panel: "logs-panel" },
    ];
    for (const { key, panel } of staticPanels) {
      await nav(page, key);
      await expect(page.getByTestId(panel)).toBeVisible({ timeout: 10000 });
    }
  });
});
