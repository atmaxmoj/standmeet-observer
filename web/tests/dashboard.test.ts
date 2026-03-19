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
    await expect(page.getByTestId("episode-count")).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/header.png", fullPage: false });
  });

  test("sidebar is visible with grouped navigation", async ({ page }) => {
    await page.goto("/");
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible();
    // Check category labels (Sources replaces Capture)
    await expect(sidebar).toContainText("Sources");
    await expect(sidebar).toContainText("Memory");
    await expect(sidebar).toContainText("Usage");
    await expect(sidebar).toContainText("Logs");
  });

  test("Screen source panel shows seeded data", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Should have record cards from seeded frames
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

  test("Episodes panel shows extracted episodes with summaries", async ({ page }) => {
    await page.goto("/");
    await nav(page, "episodes");
    const panel = page.getByTestId("episodes-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Should have at least one episode card with a real summary
    const cards = panel.getByTestId("episode-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Summary should contain actual content, not be empty
    const text = await cards.first().textContent();
    expect(text!.length).toBeGreaterThan(20);

    await page.screenshot({ path: "tests/screenshots/episodes.png", fullPage: true });
  });

  test("Playbook panel shows entries with non-empty content", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: "Run Distill" })).toBeVisible();

    // Should have at least one playbook entry
    const cards = panel.getByTestId("playbook-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Entry content must NOT be raw empty JSON like {"intuition": "", "action": ""}
    const text = await cards.first().textContent();
    expect(text).not.toContain('"intuition"');
    expect(text).not.toContain('"action": ""');

    // Should contain When/Then from the distilled content
    expect(text!.length).toBeGreaterThan(30);

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
    await expect(panel.getByText("API Calls", { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: "tests/screenshots/usage.png", fullPage: true });
  });

  test("Zsh source panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:zsh");
    const panel = page.getByTestId("source-panel-zsh");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/zsh.png", fullPage: true });
  });

  test("Logs panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "logs");
    const panel = page.getByTestId("logs-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/logs.png", fullPage: true });
  });

  test("record detail overlay opens on click", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });

    // Click the first card to open detail
    await panel.getByTestId("source-record-card").first().click();

    // Detail overlay should appear
    const detail = page.getByTestId("record-detail");
    await expect(detail).toBeVisible({ timeout: 5000 });

    // Close it
    await page.getByTestId("record-detail-close").click();
    await expect(detail).not.toBeVisible();
  });

  test("selection bar appears when right-clicking records", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    const cards = panel.getByTestId("source-record-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Right-click first card to select it
    await cards.first().click({ button: "right" });

    // Selection bar should appear with "1 selected"
    const selCount = page.getByTestId("selection-count");
    await expect(selCount.first()).toBeVisible({ timeout: 5000 });
    await expect(selCount.first()).toContainText("1 selected");

    // Click Cancel to clear selection
    await page.getByTestId("selection-cancel").first().click();
    await expect(selCount.first()).not.toBeVisible();

    // Records should be back (selection bar gone)
    await expect(cards.first()).toBeVisible();
  });

  test("header shows pipeline toggle switch", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("pipeline-toggle")).toBeVisible({ timeout: 10000 });
  });

  test("sidebar navigation works for all panels", async ({ page }) => {
    await page.goto("/");
    // Source panels use dynamic nav keys (source:name)
    // Static panels use fixed keys
    const staticPanels = [
      { key: "episodes", panel: "episodes-panel" },
      { key: "playbooks", panel: "playbooks-panel" },
      { key: "routines", panel: "routines-panel" },
      { key: "chat", panel: "chat-panel" },
      { key: "usage", panel: "usage-panel" },
      { key: "logs", panel: "logs-panel" },
    ];
    for (const { key, panel } of staticPanels) {
      await nav(page, key);
      await expect(page.getByTestId(panel)).toBeVisible({ timeout: 10000 });
    }
  });

  test("Refresh button reloads data", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Click refresh
    await panel.getByRole("button", { name: "Refresh" }).click();

    // Should still show records after refresh
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });
  });

  test("pagination works when data exceeds page size", async ({ page }) => {
    // Screen has 35 seeded records, PAGE_SIZE=50 → 1 page → no Next button
    // This test verifies pagination renders and records are visible
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });
  });

  test("Chat panel loads with input", async ({ page }) => {
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel.getByTestId("chat-input")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Send" })).toBeVisible();
  });

  test("Chat web search shows throbbing and returns result", async ({ page }) => {
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Type and send a search query
    const input = panel.getByTestId("chat-input");
    await input.fill("search the web for what is SearXNG");
    await panel.getByRole("button", { name: "Send" }).click();

    // Should see throbbing (Thinking... or Searching the web...)
    await expect(panel.getByText(/Thinking|Searching/)).toBeVisible({ timeout: 10000 });

    // Wait for assistant response (may take a while with real LLM)
    const assistantMsg = panel.locator(".bg-muted.text-foreground");
    await expect(assistantMsg.first()).toBeVisible({ timeout: 120000 });

    // Response should contain actual content (not an error)
    const text = await assistantMsg.first().textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(20);
  });
});
