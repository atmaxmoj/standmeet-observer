import { test, expect } from "@playwright/test";
import { nav } from "./helpers";

test.describe("Chat", () => {
  test("Chat queries data with tools before answering", async ({ page }) => {
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

    const clearBtn = panel.getByText("Clear chat");
    if (await clearBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await clearBtn.click();
      await page.waitForTimeout(500);
    }

    const assistantMsg = panel.locator(".bg-muted.text-foreground");
    await expect(assistantMsg).toHaveCount(0, { timeout: 3000 }).catch(() => {/* may have history */});

    const input = panel.getByTestId("chat-input");
    await input.fill("How have I been doing lately? Look at my recent episodes and playbooks.");
    await panel.getByRole("button", { name: "Send" }).click();

    await expect(panel.getByText(/Thinking|Searching|Reading/)).toBeVisible({ timeout: 15000 });
    await expect(assistantMsg.first()).toBeVisible({ timeout: 60000 });

    const text = await assistantMsg.first().textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(30);
    expect(text).not.toContain("LLM call failed");
  });

  test("Chat web search shows throbbing and returns result", async ({ page }) => {
    await page.goto("/");
    await nav(page, "chat");
    const panel = page.getByTestId("chat-panel");
    await expect(panel).toBeVisible({ timeout: 10000 });

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
});
