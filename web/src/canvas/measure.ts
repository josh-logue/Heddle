// The browser's text measurer for board/text.ts: canvas measureText, cached per font.

import { FONTS, cssFont, type FontKey, type TextMeasurer } from "../board/text.ts";

export function canvasMeasurer(): TextMeasurer {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const widths = new Map<string, Map<string, number>>();
  const metrics = new Map<FontKey, [number, number]>();
  const vertical = (font: FontKey): [number, number] => {
    let v = metrics.get(font);
    if (!v) {
      ctx.font = cssFont(font);
      const tm = ctx.measureText("Mg");
      // The font's own line box (as Qt's ascent and descent), not just these glyphs.
      v = [tm.fontBoundingBoxAscent || FONTS[font].size, tm.fontBoundingBoxDescent || FONTS[font].size / 4];
      metrics.set(font, v);
    }
    return v;
  };
  return {
    width(text, font) {
      let cache = widths.get(font);
      if (!cache) widths.set(font, (cache = new Map()));
      let w = cache.get(text);
      if (w === undefined) {
        ctx.font = cssFont(font);
        w = ctx.measureText(text).width;
        if (cache.size > 20000) cache.clear();
        cache.set(text, w);
      }
      return w;
    },
    ascent: (font) => vertical(font)[0],
    descent: (font) => vertical(font)[1],
  };
}
