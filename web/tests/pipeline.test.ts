import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Pipeline", () => {
  test("Run Distill triggers Opus and produces new entries", async ({ page }) => {
    await page.goto("/");
    await nav(page, "playbooks");
    const panel = page.getByTestId("playbooks-panel");
    await expect(panel.getByTestId("playbook-card").first()).toBeVisible({ timeout: 10000 });

    page.on("dialog", (d) => d.accept());
    await panel.getByRole("button", { name: "Run Distill" }).click();

    await expect(panel.getByRole("button", { name: "Run Distill" })).toBeEnabled({ timeout: 360000 });

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

    page.on("dialog", (d) => d.accept());
    await panel.getByRole("button", { name: "Run Compose" }).click();

    await expect(panel.getByRole("button", { name: "Run Compose" })).toBeEnabled({ timeout: 360000 });

    await panel.getByRole("button", { name: "Refresh" }).click();
  });

  test("Run DA triggers Opus and produces insights", async ({ page }) => {
    await page.goto("/");
    await nav(page, "insights");
    const panel = page.getByTestId("insights-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    await panel.getByRole("button", { name: "Run DA" }).click();

    await expect(panel.getByRole("button", { name: "Run DA" })).toBeEnabled({ timeout: 360000 });

    await expect(panel.getByTestId("insight-card").first()).toBeVisible({ timeout: 10000 });
    const count = await panel.getByTestId("insight-card").count();
    expect(count).toBeGreaterThan(0);
  });

  test("Pipeline toggle changes state on click", async ({ page }) => {
    await page.goto("/");
    const toggle = page.getByTestId("pipeline-toggle");
    await expect(toggle).toBeVisible({ timeout: 10000 });

    const pausedBefore = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });

    await toggle.click();
    await page.waitForTimeout(2000);

    const pausedAfter = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });
    expect(pausedAfter).not.toBe(pausedBefore);

    await toggle.click();
    await page.waitForTimeout(2000);

    const pausedRestored = await page.evaluate(async () => {
      const r = await fetch("/api/engine/pipeline");
      return (await r.json()).paused;
    });
    expect(pausedRestored).toBe(pausedBefore);
  });
});
