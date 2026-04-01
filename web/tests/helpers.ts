import type { Page } from "@playwright/test";

/** Click a sidebar nav item by its data-testid */
export async function nav(page: Page, key: string) {
  await page.getByTestId(`nav-${key}`).click();
}
