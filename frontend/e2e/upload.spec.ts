import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

const photo = fileURLToPath(new URL("./fixtures/shirt.jpg", import.meta.url));

test("a new user uploads a photo and the batch is saved", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "e2e-password-123";

  await page.goto("/");
  await page.getByRole("button", { name: "New here? Create an account" }).click();
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password (8+ characters)").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(photo);
  await expect(page.getByText("1 photo ready")).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page).toHaveURL(/#\/batches\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Batch of 1 photo", exact: true })).toBeVisible();
  await expect(page.getByText("shirt.jpg", { exact: true })).toBeVisible();

  const batchUrl = page.url();
  await page.reload();
  await expect(page).toHaveURL(batchUrl);
  await expect(page.getByRole("heading", { name: "Batch of 1 photo", exact: true })).toBeVisible();
  await expect(page.getByText("shirt.jpg", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "AI Catalog Assistant" }).click();
  await expect(page.locator('a[href^="#/batches/"]')).toHaveCount(1);
});