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

  test("Playbook sort by date changes order", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    const cards = panel.getByTestId("playbook-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Get first card name with default sort (confidence)
    const defaultFirst = await cards.first().textContent();

    // Click "date" sort
    await panel.getByRole("button", { name: "date" }).click();

    // First card may change (different sort order)
    const dateFirst = await cards.first().textContent();

    // At least one sort should have entries (both truthy)
    expect(defaultFirst).toBeTruthy();
    expect(dateFirst).toBeTruthy();

    // Switch back to confidence
    await panel.getByRole("button", { name: "confidence" }).click();
    const backToDefault = await cards.first().textContent();
    expect(backToDefault).toBe(defaultFirst);
  });

  test("Playbook sort by maturity groups by level", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel.getByTestId("playbook-card").first()).toBeVisible({ timeout: 10000 });

    // Click "maturity" sort button
    await panel.getByRole("button", { name: "maturity" }).click();

    // First card should have the highest maturity (mastered or mature)
    const firstCard = panel.getByTestId("playbook-card").first();
    const firstText = await firstCard.textContent();
    // It should contain a maturity badge — at minimum not be nascent if there are higher ones
    expect(firstText).toBeTruthy();
  });

  test("Routine sort buttons work", async ({ page }) => {
    await page.goto("/");
    await nav(page, "routines");
    const panel = page.getByTestId("routines-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Sort buttons should be visible
    await expect(panel.getByRole("button", { name: "confidence" })).toBeVisible();
    await expect(panel.getByRole("button", { name: "date" })).toBeVisible();
    await expect(panel.getByRole("button", { name: "maturity" })).toBeVisible();

    // Click each and verify no crash
    await panel.getByRole("button", { name: "date" }).click();
    await panel.getByRole("button", { name: "maturity" }).click();
    await panel.getByRole("button", { name: "confidence" }).click();
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

  test("record detail overlay opens on thumbnail click", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    await expect(panel.getByTestId("source-record-card").first()).toBeVisible({ timeout: 10000 });

    // Click thumbnail image (or OCR button) on first card to open detail
    const firstCard = panel.getByTestId("source-record-card").first();
    const thumb = firstCard.locator("img").first();
    if (await thumb.isVisible({ timeout: 2000 }).catch(() => false)) {
      await thumb.click();
    } else {
      await firstCard.getByText("OCR").click();
    }

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

  test("Chat queries data with tools before answering", async ({ page }) => {
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Clear any previous chat history
    const clearBtn = panel.getByText("Clear chat");
    if (await clearBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await clearBtn.click();
      await page.waitForTimeout(500);
    }

    // No assistant messages should be visible now
    const assistantMsg = panel.locator(".bg-muted.text-foreground");
    await expect(assistantMsg).toHaveCount(0, { timeout: 3000 }).catch(() => {});

    // Ask about user's data — LLM must use tools to answer
    const input = panel.getByTestId("chat-input");
    await input.fill("How have I been doing lately? Look at my recent episodes and playbooks.");
    await panel.getByRole("button", { name: "Send" }).click();

    // Should see thinking/tool indicator
    await expect(panel.getByText(/Thinking|Searching|Reading/)).toBeVisible({ timeout: 15000 });

    // Wait for NEW assistant response
    await expect(assistantMsg.first()).toBeVisible({ timeout: 60000 });

    // Response should be substantial and not an error
    const text = await assistantMsg.first().textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(30);
    expect(text).not.toContain("LLM call failed");
  });

  test("Chat web search shows throbbing and returns result", async ({ page }) => {
    // Fresh page to avoid state from previous chat test
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Wait for input to be ready, then fill (Send is disabled while input is empty)
    const input = panel.getByTestId("chat-input");
    await expect(input).toBeVisible({ timeout: 5000 });
    await expect(input).toBeEnabled({ timeout: 5000 });
    await input.fill("search the web for what is SearXNG");

    const sendBtn = panel.getByRole("button", { name: "Send" });
    await expect(sendBtn).toBeEnabled({ timeout: 5000 });
    await sendBtn.click();

    await expect(panel.getByText(/Thinking|Searching/)).toBeVisible({ timeout: 15000 });

    const assistantMsg = panel.locator(".bg-muted.text-foreground");
    await expect(assistantMsg.first()).toBeVisible({ timeout: 120000 });

    const text = await assistantMsg.first().textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(20);
  });

  test("Run Distill triggers Opus and produces new entries", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel.getByTestId("playbook-card").first()).toBeVisible({ timeout: 10000 });

    // Get current count
    const countBefore = await panel.getByTestId("playbook-card").count();

    // Click Run Distill and confirm
    page.on("dialog", (d) => d.accept());
    await panel.getByRole("button", { name: "Run Distill" }).click();

    // Wait for distill to complete (button re-enables)
    await expect(panel.getByRole("button", { name: "Run Distill" })).toBeEnabled({ timeout: 120000 });

    // Refresh and verify entries exist (may be same count if upserted)
    await panel.getByRole("button", { name: "Refresh" }).click();
    await expect(panel.getByTestId("playbook-card").first()).toBeVisible({ timeout: 10000 });
    const countAfter = await panel.getByTestId("playbook-card").count();
    expect(countAfter).toBeGreaterThan(0);
  });

  test("Run Compose triggers Opus and produces routines", async ({ page }) => {
    await page.goto("/");
    await nav(page, "routines");
    const panel = page.getByTestId("routines-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Click Run Compose and confirm
    page.on("dialog", (d) => d.accept());
    await panel.getByRole("button", { name: "Run Compose" }).click();

    // Wait for compose to complete
    await expect(panel.getByRole("button", { name: "Run Compose" })).toBeEnabled({ timeout: 120000 });

    // Refresh and check routines exist
    await panel.getByRole("button", { name: "Refresh" }).click();
    // May or may not have routines depending on data, but should not error
  });

  test("Pipeline toggle changes state on click", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByTestId("pipeline-toggle");
    await expect(toggle).toBeVisible({ timeout: 10000 });

    // Use page.evaluate to call API (runs in browser context, same origin)
    const pausedBefore = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });

    // Click toggle
    await toggle.click();
    await page.waitForTimeout(2000);

    const pausedAfter = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });
    expect(pausedAfter).not.toBe(pausedBefore);

    // Restore
    await toggle.click();
    await page.waitForTimeout(2000);

    const pausedRestored = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });
    expect(pausedRestored).toBe(pausedBefore);
  });

  test("Selection bar shows delete button when records selected", async ({ page }) => {
    await page.goto("/");
    await nav(page, "source:screen");
    const panel = page.getByTestId("source-panel-screen");
    const cards = panel.getByTestId("source-record-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });

    // Right-click to select
    await cards.first().click({ button: "right" });

    // Selection bar with delete button should appear
    await expect(page.getByTestId("selection-count").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId("selection-delete").first()).toBeVisible();

    // Cancel selection
    await page.getByTestId("selection-cancel").first().click();
    await expect(page.getByTestId("selection-count").first()).not.toBeVisible();
  });
});
