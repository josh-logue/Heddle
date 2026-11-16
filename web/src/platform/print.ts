// "PDF" on the web: the board as SVG in a hidden frame, handed to the browser's Print, where
// "Save as PDF" keeps it sharp (no PDF library needed; decided in W7).

/** Print an SVG drawing on its own, one page sized to fit. */
export function printSvg(svg: string, title: string): void {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  const body = svg.replace(/^<\?xml[^>]*>\s*/, "");
  const esc = title.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><title>${esc}</title><style>
@page { margin: 10mm; }
html, body { margin: 0; }
svg { display: block; width: 100%; height: auto; max-height: 100vh; }
</style></head><body>${body}</body></html>`;
  frame.addEventListener("load", () => {
    const w = frame.contentWindow;
    if (!w) return;
    const done = () => setTimeout(() => frame.remove(), 1000);
    w.addEventListener("afterprint", done, { once: true });
    w.focus();
    w.print();
    setTimeout(() => frame.isConnected && frame.remove(), 10 * 60_000); // in case afterprint never comes
  }, { once: true });
  document.body.appendChild(frame);
}
