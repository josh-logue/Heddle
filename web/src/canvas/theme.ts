// Light and dark colours for the canvas, cards and arrows (heddle/theme.py), and the
// QColor helpers the drawing code leans on (lighter, darker, alpha).

export interface Theme {
  dark: boolean;
  canvasBg: string;
  gridMinor: string;
  gridMajor: string;
  cardBg: string;
  cardBorder: string;
  cardText: string;
  cardMuted: string;
  cardShadow: string;
  portRing: string;
  edgeLine: string;
  edgeHover: string;
  edgeLabelBg: string;
  edgeText: string;
  selected: string;
  highlight: string;
}

export const LIGHT: Theme = {
  dark: false,
  canvasBg: "#f3f1ec",
  gridMinor: "#e7e4dc",
  gridMajor: "#d9d5cb",
  cardBg: "#fffdf8",
  cardBorder: "#cfcac0",
  cardText: "#2b2b2b",
  cardMuted: "#8a857c",
  cardShadow: "rgba(0,0,0,0.137)",
  portRing: "#ffffff",
  edgeLine: "#8a857c",
  edgeHover: "#4f4b45",
  edgeLabelBg: "#fffdf8",
  edgeText: "#2b2b2b",
  selected: "#ff8c1a",
  highlight: "#1f8a96",
};

export const DARK: Theme = {
  dark: true,
  canvasBg: "#1c1d20",
  gridMinor: "#24262a",
  gridMajor: "#2e3035",
  cardBg: "#2c2e33",
  cardBorder: "#43464d",
  cardText: "#e4e4e6",
  cardMuted: "#9b9ea6",
  cardShadow: "rgba(0,0,0,0.47)",
  portRing: "#1c1d20",
  edgeLine: "#8c9099",
  edgeHover: "#c9ccd3",
  edgeLabelBg: "#2c2e33",
  edgeText: "#e4e4e6",
  selected: "#ff9d3d",
  highlight: "#4cc3cf",
};

export type RGB = [number, number, number];

export function parseHex(hex: string): RGB {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export function toHex([r, g, b]: RGB): string {
  return "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
}

/** A colour with an alpha of 0 to 255, as QColor.setAlpha. */
export function withAlpha(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex);
  return `rgba(${r},${g},${b},${(alpha / 255).toFixed(3)})`;
}

function toHsv([r, g, b]: RGB): [number, number, number] {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return [h, max ? (d / max) * 255 : 0, max];
}

function fromHsv(h: number, s: number, v: number): RGB {
  const sat = s / 255;
  const c = v * sat;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r + m, g + m, b + m];
}

/** QColor.lighter(factor): brighter in HSV value, losing saturation past white. */
export function lighter(hex: string, factor: number): string {
  const [h, s0, v0] = toHsv(parseHex(hex));
  let s = s0;
  let v = (v0 * factor) / 100;
  if (v > 255) {
    s = Math.max(0, s - (v - 255));
    v = 255;
  }
  return toHex(fromHsv(h, s, v));
}

/** QColor.darker(factor). */
export function darker(hex: string, factor: number): string {
  const [h, s, v] = toHsv(parseHex(hex));
  return toHex(fromHsv(h, s, (v * 100) / factor));
}

/** Dark text on light header colours, white on dark ones (card_item.readable_text_color). */
export function readableText(hex: string): string {
  const [r, g, b] = parseHex(hex);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.62 ? "#1e1e1e" : "#ffffff";
}
