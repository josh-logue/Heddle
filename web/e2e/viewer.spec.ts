// The viewer in a real browser: opening boards, pan and zoom, folding and details.
import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

const shots = process.env.HEDDLE_SHOTS; // a folder: save screenshots there to look at

async function shot(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
}

const zoomText = (page: Page) => page.locator(".zoom").innerText();

test("opens a demo from a link and draws it", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await expect(page).toHaveTitle("Lantern Tide · Heddle");
  await expect(page.locator(".minimap canvas")).toBeVisible();
  await shot(page, "lantern-fit");
  expect(errors).toEqual([]);
});

test("the welcome page opens a demo", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Heddle" })).toBeVisible();
  await shot(page, "welcome");
  await page.getByRole("button", { name: /Hollybank Garden/ }).first().click();
  await expect(page.locator(".board-name")).toHaveText("Hollybank Garden");
  expect(new URL(page.url()).searchParams.get("demo")).toBe("hollybank-garden");
  await shot(page, "hollybank-fit");
});

test("zooms with Ctrl+wheel and the buttons, and pans by dragging", async ({ page }) => {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  const canvas = page.locator(".board-canvas");
  await page.getByRole("button", { name: /%$/ }).click(); // actual size
  await expect(page.locator(".zoom")).toHaveText("100%");
  await canvas.hover({ position: { x: 600, y: 400 } });
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -100);
  await page.keyboard.up("Control");
  await expect(page.locator(".zoom")).toHaveText("115%");
  await page.getByRole("button", { name: "Zoom out" }).click();
  await expect(page.locator(".zoom")).toHaveText("100%");
  await shot(page, "lantern-100");
  const before = await canvas.screenshot();
  await page.mouse.move(600, 400);
  await page.mouse.down({ button: "middle" }); // (a left drag would move a card)
  await page.mouse.move(450, 300, { steps: 5 });
  await page.mouse.up({ button: "middle" });
  expect(Buffer.compare(before, await canvas.screenshot())).not.toBe(0);
  await page.keyboard.press("Control+0");
  expect(await zoomText(page)).toBe("100%");
});

test("folds every group and shows every card's details", async ({ page }) => {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  const view = page.getByText("View", { exact: true });
  await view.click();
  await page.getByRole("button", { name: /Expand every group/ }).click(); // World Notes starts folded
  await view.click();
  await page.getByRole("button", { name: /Collapse every group/ }).click();
  await expect(page.getByRole("button", { name: /Expand every group/ })).toBeHidden(); // picking closes the menu
  await view.click();
  await expect(page.getByRole("button", { name: /Expand every group/ })).toBeVisible();
  await page.mouse.click(600, 500); // so does a click elsewhere
  await expect(page.getByRole("button", { name: /Expand every group/ })).toBeHidden();
  await shot(page, "lantern-collapsed");
  await page.keyboard.press("Shift+C");
  await view.click();
  await expect(page.getByRole("button", { name: /Collapse every group/ })).toBeVisible();
  await page.getByRole("button", { name: /Show every card's details/ }).click();
  await view.click();
  await expect(page.getByRole("button", { name: /Hide every card's details/ })).toBeVisible();
  await view.click();
  await shot(page, "lantern-details");
});

test("opens a board file, and says when a file isn't a board", async ({ page }) => {
  // Without the File System Access API (as in Firefox and Safari): a plain file input.
  await page.addInitScript(() => delete (window as { showOpenFilePicker?: unknown }).showOpenFilePicker);
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Open a board…" }).click();
  await (await chooser).setFiles(fileURLToPath(new URL("../../examples/hollybank-garden.json", import.meta.url)));
  await expect(page.locator(".board-name")).toHaveText("hollybank-garden");
  const again = page.waitForEvent("filechooser");
  await page.getByText("File", { exact: true }).click();
  await page.getByRole("button", { name: /^Open…/ }).click();
  await (await again).setFiles({ name: "notes.json", mimeType: "application/json", buffer: Buffer.from("{oops") });
  await expect(page.getByRole("alert")).toContainText("“notes.json” isn't a Heddle board");
});

test("dark theme", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /%$/ }).click();
  await shot(page, "lantern-dark-100");
});

/** Where a point on a card (card coordinates) is on the page. */
async function onCard(page: Page, title: string, part: "toggle" | "fold") {
  return page.evaluate(([t, which]) => {
    type Canvas = {
      store: { boxes: Map<string, { card: { title: string }; x: number; y: number; w: number }> };
      camera: { toScreen(x: number, y: number): [number, number] };
      canvas: HTMLCanvasElement;
    };
    const c = (window as unknown as { heddleCanvas: Canvas }).heddleCanvas;
    const box = [...c.store.boxes.values()].find((b) => b.card.title === t)!;
    const [lx, ly] = which === "toggle" ? [box.w - 10 - 18 + 4 + 9, 16] : [6 + 8, 16];
    const [sx, sy] = c.camera.toScreen(box.x + lx, box.y + ly);
    const r = c.canvas.getBoundingClientRect();
    return { x: r.left + sx, y: r.top + sy };
  }, [title, part] as const);
}

test("clicking a card's ▸ shows its details, and a group's − folds it", async ({ page }) => {
  await page.goto("/?demo=lantern-tide");
  await expect(page.locator(".board-name")).toHaveText("Lantern Tide");
  await page.getByRole("button", { name: /%$/ }).click();
  const height = () => page.evaluate(() => {
    const c = (window as unknown as { heddleCanvas: { store: { boxes: Map<string, { card: { title: string }; h: number }> } } }).heddleCanvas;
    return [...c.store.boxes.values()].find((b) => b.card.title === "The Warden Hall")!.h;
  });
  const closed = await height();
  const toggle = await onCard(page, "The Warden Hall", "toggle");
  await page.mouse.move(toggle.x, toggle.y);
  await expect(page.locator(".tooltip")).toHaveText("Show details");
  await page.mouse.click(toggle.x, toggle.y);
  expect(await height()).toBeGreaterThan(closed);
  await shot(page, "warden-hall-details");
  await page.mouse.click(toggle.x, toggle.y);
  expect(await height()).toBe(closed);

  const fold = await onCard(page, "The Warden's Road", "fold");
  await page.mouse.click(fold.x, fold.y);
  await page.getByText("View", { exact: true }).click();
  await expect(page.getByRole("button", { name: /Expand every group/ })).toBeVisible();
});
