// Export as PDF in the desktop shell (W9e): the native Save dialog, then one page the
// board's shape at actual size (shrunk past 200 inches a side), as the Python app's.
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { answerDialog, launch, makeProfile, quit, type Profile } from "./shell.ts";

let profile: Profile;
test.beforeEach(() => {
  profile = makeProfile();
});
test.afterEach(() => profile.remove());

const board = (cards: { title: string; x: number; y: number }[]) =>
  JSON.stringify({ app: "Heddle", version: 12, cards: cards.map((c, i) => ({ id: `c${i}`, ...c })), connections: [] });

/** File → Export board as image → PDF, saved where the dialog says (null: cancelled). */
async function exportPdf(app: ElectronApplication, page: Page, file: string | null) {
  await answerDialog(app, "save", file);
  await page.getByText("File", { exact: true }).click();
  await page.getByRole("button", { name: /Export board as image/ }).click();
  const dialog = page.getByRole("dialog", { name: "Export board as image" });
  await dialog.getByLabel(/PDF document/).check();
  await dialog.getByRole("button", { name: "Export…" }).click();
}

/** Pages and page size (points) of a PDF Chromium wrote. */
function pdfInfo(file: string): { pages: number; box: number[] } {
  const text = readFileSync(file).toString("latin1");
  const box = /\/MediaBox\s*\[\s*([\d.\s-]+)\]/.exec(text)?.[1]?.trim().split(/\s+/).map(Number) ?? [];
  return { pages: (text.match(/\/Type\s*\/Page\b/g) ?? []).length, box };
}

test("exports one page the board's shape, and nothing when cancelled", async () => {
  const tracks = path.join(profile.boards, "Tracks.json");
  writeFileSync(tracks, board([{ title: "Rowan", x: 0, y: 0 }, { title: "Mabel", x: 600, y: 300 }]));
  const { app, page } = await launch(profile, [tracks]);
  try {
    await expect(page).toHaveTitle("Tracks · Heddle");
    const out = path.join(profile.boards, "Tracks.pdf");
    await exportPdf(app, page, null);
    await page.waitForTimeout(300);
    expect(existsSync(out)).toBe(false);

    await exportPdf(app, page, out);
    await expect(page.locator(".notice, [role=status]").filter({ hasText: "Exported “Tracks.pdf”." }).first()).toBeVisible();
    expect(readFileSync(out).subarray(0, 5).toString()).toBe("%PDF-");
    const { pages, box } = pdfInfo(out);
    expect(pages).toBe(1);
    const [, , w, h] = box as [number, number, number, number];
    // Wider than tall, as the board; at actual size (0.75 pt per board unit), a little
    // bigger than the cards' spread for their own size and the margin.
    expect(w).toBeGreaterThan(h);
    expect(w).toBeGreaterThan(600 * 0.75);
    expect(w).toBeLessThan(2000 * 0.75);
  } finally {
    await quit(app);
  }
});

test("a huge board's PDF is shrunk to 200 inches on its longer side", async () => {
  const wide = path.join(profile.boards, "Wide.json");
  writeFileSync(wide, board([{ title: "West", x: 0, y: 0 }, { title: "East", x: 30000, y: 200 }]));
  const { app, page } = await launch(profile, [wide]);
  try {
    await expect(page).toHaveTitle("Wide · Heddle");
    const out = path.join(profile.boards, "Wide.pdf");
    await exportPdf(app, page, out);
    await expect.poll(() => existsSync(out), { timeout: 20_000 }).toBe(true);
    const { pages, box } = pdfInfo(out);
    expect(pages).toBe(1);
    expect(box[2]).toBeCloseTo(14400, -1); // 200 in × 72 pt
  } finally {
    await quit(app);
  }
});
