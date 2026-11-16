// Help: F1 or the ? button shows the controls, with a box to find one.
import { expect, test } from "@playwright/test";

test("F1 and ? show the controls, and the box finds one", async ({ page }) => {
  await page.goto("/");
  // The page's keys are taken once it has started (set up with this test hook).
  await page.waitForFunction(() => "heddleCanvas" in window);
  await page.keyboard.press("F1"); // works before any board is open
  const help = page.getByRole("dialog", { name: "Heddle controls" });
  await expect(help.getByRole("heading", { name: "Keys the browser keeps" })).toBeVisible();
  await help.getByLabel("Find a control").fill("thread");
  await expect(help.locator(".help-entry dt")).toContainText(["Character thread"]);
  await expect(help.getByRole("heading", { name: "Groups" })).toHaveCount(0);
  if (process.env.HEDDLE_SHOTS) await page.screenshot({ path: `${process.env.HEDDLE_SHOTS}/help.png` });
  await help.getByRole("button", { name: "Close" }).click();
  await expect(help).toHaveCount(0);
  await page.getByRole("button", { name: "Help" }).click();
  await expect(page.getByRole("dialog", { name: "Heddle controls" })).toBeVisible();
});
