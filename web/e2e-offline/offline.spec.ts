// The published site keeps working without a connection once it has been visited, and is
// installable (a web app manifest with icons).
import { expect, test } from "@playwright/test";

test("works offline after the first visit, demo boards included", async ({ page, context }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      await new Promise((r) => navigator.serviceWorker.addEventListener("controllerchange", r, { once: true }));
    }
  });
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
  await page.getByRole("button", { name: /Lantern Tide/ }).first().click();
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.goto("./?demo=hollybank-garden"); // a link straight to a demo, offline
  await expect(page.locator(".board-name")).toHaveText("Hollybank Garden");
  await context.setOffline(false);
});

test("is installable: a manifest with icons", async ({ page, request }) => {
  await page.goto("./");
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBe("/Heddle/manifest.webmanifest");
  const manifest = await (await request.get(href!)).json() as { name: string; display: string; icons: { src: string; sizes: string }[] };
  expect(manifest.name).toBe("Heddle");
  expect(manifest.display).toBe("standalone");
  for (const icon of manifest.icons) expect((await request.get(`/Heddle/${icon.src}`)).ok()).toBe(true);
  expect(manifest.icons.map((i) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
});
