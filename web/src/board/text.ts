// Text measuring, wrapping and eliding: what Qt's QFontMetricsF and QTextLayout did for
// the desktop cards (heddle/card_item.py). Pure: the measurer is passed in, so tests use
// a fake one and the browser a canvas one (canvas/measure.ts).

/** The fonts the board draws with. Sizes are Qt's point sizes at 96 dpi (pt × 4/3). */
export const FONTS = {
  title: { size: 14, bold: true, italic: false },      // 10.5 pt
  body: { size: 38 / 3, bold: false, italic: false },  // 9.5 pt
  placeholder: { size: 38 / 3, bold: false, italic: true },
  small: { size: 34 / 3, bold: false, italic: false }, // 8.5 pt
  smallItalic: { size: 34 / 3, bold: false, italic: true },
  label: { size: 10, bold: true, italic: false },      // 7.5 pt
  edge: { size: 34 / 3, bold: false, italic: false },  // arrow labels, 8.5 pt
} as const;
export type FontKey = keyof typeof FONTS;

/** Windows' UI font first, so card sizes match the desktop app there. */
export const FONT_FAMILY = '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';

export function cssFont(key: FontKey): string {
  const f = FONTS[key];
  return `${f.italic ? "italic " : ""}${f.bold ? "bold " : ""}${f.size}px ${FONT_FAMILY}`;
}

export interface TextMeasurer {
  width(text: string, font: FontKey): number;
  /** Distance from the top of a line to its baseline. */
  ascent(font: FontKey): number;
  /** Below the baseline. A line is ascent + descent tall (Qt's QFontMetricsF.height). */
  descent(font: FontKey): number;
}

export function lineHeight(m: TextMeasurer, font: FontKey): number {
  return m.ascent(font) + m.descent(font);
}

export const ELLIPSIS = "…";

/** Qt's elidedText(…, ElideRight, width): the text if it fits, else the longest start
 *  of it that fits with "…" after it. */
export function elide(m: TextMeasurer, text: string, font: FontKey, width: number): string {
  if (m.width(text, font) <= width) return text;
  const chars = Array.from(text);
  let lo = 0;
  let hi = chars.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (m.width(chars.slice(0, mid).join("") + ELLIPSIS, font) <= width) lo = mid;
    else hi = mid - 1;
  }
  return lo === 0 && m.width(ELLIPSIS, font) > width ? "" : chars.slice(0, lo).join("") + ELLIPSIS;
}

/** Break text into lines no wider than `width`: at line breaks, then at spaces, and
 *  mid-word for a word too long for a line (Qt's WrapAtWordBoundaryOrAnywhere). Spaces
 *  at the end of a line don't count towards its width and are dropped. */
export function wrapLines(m: TextMeasurer, text: string, font: FontKey, width: number): string[] {
  const out: string[] = [];
  for (const para of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!para) {
      out.push("");
      continue;
    }
    // Words with the spaces after them, so lines keep their inner spacing.
    const tokens = para.match(/\S+\s*|\s+/g) ?? [];
    let line = "";
    for (const token of tokens) {
      if (line && m.width((line + token).trimEnd(), font) > width) {
        out.push(line.trimEnd());
        line = "";
      }
      if (line) {
        line += token;
        continue;
      }
      // A fresh line. A word too long for any line breaks wherever it has to.
      let rest = token;
      while (rest.trimEnd() && m.width(rest.trimEnd(), font) > width) {
        const cut = fitChars(m, rest, font, width);
        out.push(rest.slice(0, cut));
        rest = rest.slice(cut);
      }
      line = rest;
    }
    out.push(line.trimEnd());
  }
  return out;
}

/** How many UTF-16 units of `text` fit in `width` (at least one character). */
function fitChars(m: TextMeasurer, text: string, font: FontKey, width: number): number {
  const chars = Array.from(text);
  let n = 1;
  while (n < chars.length && m.width(chars.slice(0, n + 1).join(""), font) <= width) n++;
  return chars.slice(0, n).join("").length;
}

/** Wrap `text` to `width` and keep at most `maxLines` lines, ending the last with "…" if
 *  anything was cut. Returns [lines, wasCut]. (heddle.card_item.elide_lines) */
export function elideLines(
  m: TextMeasurer, text: string, font: FontKey, width: number, maxLines: number,
): [string[], boolean] {
  const lines = wrapLines(m, text, font, width);
  if (lines.length <= maxLines) return [lines, false];
  // The rest, from the last line kept, on one line.
  const kept = lines.slice(0, maxLines - 1);
  const rest = lines.slice(maxLines - 1).join(" ").split(/\s+/).filter(Boolean).join(" ");
  let last = elide(m, rest, font, width);
  if (!last.endsWith(ELLIPSIS)) {
    // It only spilled onto more lines because of line breaks: cut at the last visible
    // line and mark the cut.
    last = elide(m, lines[maxLines - 1]! + ELLIPSIS, font, width);
  }
  return [[...kept, last], true];
}

/** A measurer for tests and Node: every character is `charWidth` × the font size / 10
 *  wide (bold a little wider), lines are 1.25 × the font size tall. */
export function fakeMeasurer(charWidth = 0.55): TextMeasurer {
  return {
    width: (text, font) => {
      const f = FONTS[font];
      return Array.from(text).length * f.size * charWidth * (f.bold ? 1.08 : 1);
    },
    ascent: (font) => FONTS[font].size,
    descent: (font) => FONTS[font].size / 4,
  };
}
