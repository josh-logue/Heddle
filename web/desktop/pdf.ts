// The board as a one-page PDF (W9e), as the Python app makes it (heddle/export_image.py):
// one page exactly the board's shape at actual size (1 board unit = 1/96 inch), shrunk if
// a side would pass 200 inches, which many readers won't open. Pure helpers here (no
// Electron, so Vitest runs them); ipc.ts prints the page with Chromium's printToPDF.

export const MAX_PDF_INCHES = 200; // 14,400 pt, as MAX_PDF_POINTS
export const UNITS_PER_INCH = 96;

export interface PdfPage {
  /** The page in inches (what printToPDF takes). */
  width: number;
  height: number;
  /** The drawing's size on the page, in CSS px (smaller than the board if shrunk). */
  cssWidth: number;
  cssHeight: number;
}

/** The page for an SVG drawing (its root's width and height, in board units), or null
 *  if it has none. */
export function pdfPage(svg: string): PdfPage | null {
  const root = /<svg\b[^>]*>/.exec(svg)?.[0] ?? "";
  const size = (name: string) => Number(new RegExp(`\\s${name}="([0-9.]+)"`).exec(root)?.[1] ?? Number.NaN);
  const w = size("width");
  const h = size("height");
  if (!(w > 0 && h > 0)) return null;
  const fit = Math.min(1, MAX_PDF_INCHES / (Math.max(w, h) / UNITS_PER_INCH));
  return { width: (w / UNITS_PER_INCH) * fit, height: (h / UNITS_PER_INCH) * fit, cssWidth: w * fit, cssHeight: h * fit };
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

/** The page that gets printed: the drawing alone, filling it edge to edge. */
export function pdfHtml(svg: string, title: string, page: PdfPage): string {
  const body = svg.replace(/^<\?xml[^>]*>\s*/, "");
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escape(title)}</title><style>
@page { size: ${page.width}in ${page.height}in; margin: 0; }
html, body { margin: 0; padding: 0; }
svg { display: block; width: ${page.cssWidth}px; height: ${page.cssHeight}px; }
</style></head><body>${body}</body></html>`;
}
