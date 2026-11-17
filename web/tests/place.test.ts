// The desktop shell's pure helpers: where a new window goes, which command-line arguments
// are boards, when two paths are one board (desktop/place.ts), and the PDF page (pdf.ts).
import path from "node:path";
import { describe, expect, it } from "vitest";
import { pdfHtml, pdfPage } from "../desktop/pdf.ts";
import { CASCADE, DEFAULT_SIZE, boardArgs, placeWindow, sameBoardPath } from "../desktop/place.ts";

const SCREEN = { x: 0, y: 0, width: 1920, height: 1040 };
const BS = String.fromCharCode(92);

describe("a new window's place", () => {
  it("cascades from the window in front, keeping its size and maximised state", () => {
    const lead = { bounds: { x: 100, y: 80, width: 1000, height: 700 }, maximized: false };
    expect(placeWindow(null, lead, [SCREEN])).toEqual({ bounds: { x: 130, y: 110, width: 1000, height: 700 }, maximized: false });
    expect(placeWindow(null, { ...lead, maximized: true }, [SCREEN]).maximized).toBe(true);
    // Cascading off the screen: on top of it instead.
    const corner = { bounds: { x: 1850, y: 980, width: 900, height: 600 }, maximized: false };
    expect(placeWindow(null, corner, [SCREEN], 200).bounds).toEqual(corner.bounds);
    expect(CASCADE).toBe(30);
  });

  it("else where the last window was, if that's still on a screen; else the default", () => {
    const saved = { bounds: { x: 200, y: 100, width: 900, height: 650 }, maximized: true };
    expect(placeWindow(saved, null, [SCREEN])).toEqual({ bounds: saved.bounds, maximized: true });
    const gone = { bounds: { x: 4000, y: 100, width: 900, height: 650 }, maximized: false }; // (a screen since unplugged)
    expect(placeWindow(gone, null, [SCREEN])).toEqual({ bounds: DEFAULT_SIZE, maximized: false });
    expect(placeWindow({ bounds: { x: Number.NaN } } as never, null, [SCREEN]).bounds).toEqual(DEFAULT_SIZE);
    expect(placeWindow(null, null, [SCREEN]).bounds).toEqual(DEFAULT_SIZE);
  });
});

describe("boards on the command line", () => {
  it("are the .json arguments after the program, resolved from where it was started", () => {
    const cwd = path.resolve("/work");
    const argv = ["Heddle.exe", "--allow-file-access", "Tracks.json", "notes.txt", path.resolve("/boards/Garden.JSON")];
    expect(boardArgs(argv, cwd, 1)).toEqual([path.join(cwd, "Tracks.json"), path.resolve("/boards/Garden.JSON")]);
    expect(boardArgs(["electron.exe", "main.ts", "a.json"], cwd, 2)).toEqual([path.join(cwd, "a.json")]);
  });
});

describe.runIf(process.platform === "win32")("one board, however its path is written", () => {
  it("ignores case and slash direction on Windows", () => {
    expect(sameBoardPath("C:/Boards/Tracks.json", ["c:", "boards", "TRACKS.json"].join(BS))).toBe(true);
    expect(sameBoardPath("C:/Boards/Tracks.json", "C:/Boards/../Boards/Tracks.json")).toBe(true);
    expect(sameBoardPath("C:/Boards/Tracks.json", "C:/Boards/Other.json")).toBe(false);
  });
});

describe("the PDF page (as the Python app's: actual size, at most 200 inches a side)", () => {
  const svg = (w: number, h: number) => `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect/></svg>`;

  it("is the board's size, 96 board units to the inch", () => {
    expect(pdfPage(svg(960, 480))).toEqual({ width: 10, height: 5, cssWidth: 960, cssHeight: 480 });
  });

  it("shrinks a huge board to 200 inches on its longer side", () => {
    const page = pdfPage(svg(96 * 400, 96 * 100))!;
    expect([page.width, page.height]).toEqual([200, 50]);
    expect([page.cssWidth, page.cssHeight]).toEqual([96 * 200, 96 * 50]);
  });

  it("has nothing for a drawing without a size", () => {
    expect(pdfPage("<svg></svg>")).toBeNull();
    expect(pdfPage(svg(0, 10))).toBeNull();
  });

  it("prints the drawing alone, edge to edge, with its title escaped", () => {
    const html = pdfHtml(svg(960, 480), "Rowan & <Mabel>", pdfPage(svg(960, 480))!);
    expect(html).toContain("@page { size: 10in 5in; margin: 0; }");
    expect(html).toContain("<title>Rowan &amp; &lt;Mabel></title>");
    expect(html).not.toContain("<?xml");
    expect(html).toContain('<svg xmlns="http://www.w3.org/2000/svg" width="960"');
  });
});
