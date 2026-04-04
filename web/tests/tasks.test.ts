import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Tasks Board", () => {
  test("Run SCM triggers Opus and produces task cards on kanban board", async ({ page }) => {
    await page.goto("/");
    await nav(page, "tasks");
    const panel = page.getByTestId("tasks-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    await panel.getByRole("button", { name: "Run SCM" }).click();

    await expect(panel.getByRole("button", { name: "Run SCM" })).toBeEnabled({ timeout: 360000 });

    // Board should have task cards
    await expect(panel.getByTestId("scm-task-card").first()).toBeVisible({ timeout: 10000 });
    const count = await panel.getByTestId("scm-task-card").count();
    expect(count).toBeGreaterThan(0);

    // Verify board columns are visible
    await expect(panel.getByText("Open")).toBeVisible();
    await expect(panel.getByText("In Progress")).toBeVisible();
    await expect(panel.getByText("Blocked")).toBeVisible();
    await expect(panel.getByText("Done")).toBeVisible();
  });

  test("Moving a task to Done updates status via API", async ({ page }) => {
    await page.goto("/");
    await nav(page, "tasks");
    const panel = page.getByTestId("tasks-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    // Ensure tasks exist
    const hasTasks = await page.evaluate(async () => {
      const r = await fetch("/api/memory/scm-tasks/");
      const data = await r.json();
      return data.tasks.length > 0;
    });
    if (!hasTasks) {
      await panel.getByRole("button", { name: "Run SCM" }).click();
      await expect(panel.getByRole("button", { name: "Run SCM" })).toBeEnabled({ timeout: 360000 });
    }

    // Get an open task
    const taskId = await page.evaluate(async () => {
      const r = await fetch("/api/memory/scm-tasks/?status=open");
      const data = await r.json();
      return data.tasks.length > 0 ? data.tasks[0].id : null;
    });

    if (taskId) {
      // Move to done via API (simulates drag-drop result)
      const updated = await page.evaluate(async (id) => {
        const r = await fetch(`/api/memory/scm-tasks/${id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "done" }),
        });
        return r.json();
      }, taskId);
      expect(updated.status).toBe("done");

      // Refresh and verify task moved
      await panel.getByRole("button", { name: "Refresh" }).click();
      await page.waitForTimeout(1000);

      const openTaskIds = await page.evaluate(async () => {
        const r = await fetch("/api/memory/scm-tasks/?status=open");
        const data = await r.json();
        return data.tasks.map((t: { id: number }) => t.id);
      });
      expect(openTaskIds).not.toContain(taskId);
    }
  });
});
