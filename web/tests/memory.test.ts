import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Memory Panels", () => {
  test("Episodes panel shows extracted episodes with summaries", async ({ page }) => {
    await page.goto("/");
    await nav(page, "episodes");
    const panel = page.getByTestId("episodes-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    const cards = panel.getByTestId("episode-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
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
    const cards = panel.getByTestId("playbook-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
    const text = await cards.first().textContent();
    expect(text).not.toContain('"intuition"');
    expect(text).not.toContain('"action": ""');
    expect(text!.length).toBeGreaterThan(30);
    await page.screenshot({ path: "tests/screenshots/playbook.png", fullPage: true });
  });

  test("Playbook sort by date changes order", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    const cards = panel.getByTestId("playbook-card");
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
    const defaultFirst = await cards.first().textContent();
    await panel.getByRole("button", { name: "date" }).click();
    const dateFirst = await cards.first().textContent();
    expect(defaultFirst).toBeTruthy();
    expect(dateFirst).toBeTruthy();
    await panel.getByRole("button", { name: "confidence" }).click();
    const backToDefault = await cards.first().textContent();
    expect(backToDefault).toBe(defaultFirst);
  });

  test("Playbook sort by maturity groups by level", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel.getByTestId("playbook-card").first()).toBeVisible({ timeout: 10000 });
    await panel.getByRole("button", { name: "maturity" }).click();
    const firstText = await panel.getByTestId("playbook-card").first().textContent();
    expect(firstText).toBeTruthy();
  });

  test("Routine sort buttons work", async ({ page }) => {
    await page.goto("/");
    await nav(page, "routines");
    const panel = page.getByTestId("routines-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await expect(panel.getByRole("button", { name: "confidence" })).toBeVisible();
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

  test("Logs panel loads", async ({ page }) => {
    await page.goto("/");
    await nav(page, "logs");
    const panel = page.getByTestId("logs-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: "tests/screenshots/logs.png", fullPage: true });
  });
});
