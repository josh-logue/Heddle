// An SVG writer that stands in for a canvas: the board's drawing code (draw.ts) runs on it
// unchanged and every call becomes an SVG element, so an SVG export looks exactly like the
// screen and stays sharp at any size (heddle/export_image.py used QSvgGenerator the same
// way). Only the parts of the Canvas 2D API that draw.ts uses are here.

type Matrix = [number, number, number, number, number, number];
const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

const num = (v: number) => (Math.abs(v) < 1e-9 ? "0" : String(Math.round(v * 1000) / 1000));

function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

export function escapeXml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** A colour as SVG wants it: [colour, opacity]. Canvas colours may be "#rrggbb",
 *  "#rrggbbaa" or "rgba(r,g,b,a)"; some SVG readers don't know the last two. */
export function svgColor(c: string): [string, number] {
  const rgba = /^rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$/i.exec(c);
  if (rgba) return [`rgb(${rgba[1]},${rgba[2]},${rgba[3]})`, Number(rgba[4])];
  const hex8 = /^#([0-9a-f]{6})([0-9a-f]{2})$/i.exec(c);
  if (hex8) return [`#${hex8[1]}`, parseInt(hex8[2]!, 16) / 255];
  return [c, 1];
}

/** A path, recorded as SVG path data (stands in for Path2D). */
export class SvgPath {
  d: string[] = [];
  private x = 0;
  private y = 0;

  moveTo(x: number, y: number): void {
    this.d.push(`M${num(x)} ${num(y)}`);
    this.x = x;
    this.y = y;
  }
  lineTo(x: number, y: number): void {
    this.d.push(`L${num(x)} ${num(y)}`);
    this.x = x;
    this.y = y;
  }
  bezierCurveTo(a: number, b: number, c: number, d: number, x: number, y: number): void {
    this.d.push(`C${num(a)} ${num(b)} ${num(c)} ${num(d)} ${num(x)} ${num(y)}`);
    this.x = x;
    this.y = y;
  }
  closePath(): void {
    this.d.push("Z");
  }
  rect(x: number, y: number, w: number, h: number): void {
    this.d.push(`M${num(x)} ${num(y)}h${num(w)}v${num(h)}h${num(-w)}Z`);
  }
  roundRect(x: number, y: number, w: number, h: number, radius: number | number[] = 0): void {
    const r = Math.min(Array.isArray(radius) ? radius[0] ?? 0 : radius, w / 2, h / 2);
    if (r <= 0) {
      this.rect(x, y, w, h);
      return;
    }
    const a = (dx: number, dy: number) => `a${num(r)} ${num(r)} 0 0 1 ${num(dx)} ${num(dy)}`;
    this.d.push(`M${num(x + r)} ${num(y)}h${num(w - 2 * r)}${a(r, r)}v${num(h - 2 * r)}${a(-r, r)}h${num(-(w - 2 * r))}${a(-r, -r)}v${num(-(h - 2 * r))}${a(r, -r)}Z`);
  }
  arc(cx: number, cy: number, r: number, start: number, end: number): void {
    this.ellipse(cx, cy, r, r, 0, start, end);
  }
  ellipse(cx: number, cy: number, rx: number, ry: number, _rotation: number, start: number, end: number): void {
    const at = (t: number): [number, number] => [cx + rx * Math.cos(t), cy + ry * Math.sin(t)];
    const [sx, sy] = at(start);
    this.d.push(`${this.d.length ? "L" : "M"}${num(sx)} ${num(sy)}`);
    const sweep = end - start;
    if (Math.abs(sweep) >= Math.PI * 2 - 1e-9) { // a full circle: two halves
      const [mx, my] = at(start + Math.PI);
      this.d.push(`A${num(rx)} ${num(ry)} 0 0 1 ${num(mx)} ${num(my)}`, `A${num(rx)} ${num(ry)} 0 0 1 ${num(sx)} ${num(sy)}`);
      [this.x, this.y] = [sx, sy];
      return;
    }
    const [ex, ey] = at(end);
    this.d.push(`A${num(rx)} ${num(ry)} 0 ${Math.abs(sweep) > Math.PI ? 1 : 0} ${sweep > 0 ? 1 : 0} ${num(ex)} ${num(ey)}`);
    [this.x, this.y] = [ex, ey];
  }

  get data(): string {
    return this.d.join("");
  }
}

interface State {
  transform: Matrix;
  fillStyle: string;
  strokeStyle: string;
  lineWidth: number;
  lineCap: CanvasLineCap;
  lineDash: number[];
  font: string;
  textAlign: CanvasTextAlign;
  globalAlpha: number;
  clip: string | null;
}

/** The canvas stand-in. Draw on it, then take `svg(width, height)`. */
export class SvgContext {
  private state: State = {
    transform: IDENTITY, fillStyle: "#000", strokeStyle: "#000", lineWidth: 1, lineCap: "butt", lineDash: [],
    font: "10px sans-serif", textAlign: "left", globalAlpha: 1, clip: null,
  };
  private stack: State[] = [];
  private path = new SvgPath();
  private readonly defs: string[] = [];
  private readonly body: string[] = [];
  private clips = 0;

  get fillStyle(): string { return this.state.fillStyle; }
  set fillStyle(v: string) { this.state.fillStyle = v; }
  get strokeStyle(): string { return this.state.strokeStyle; }
  set strokeStyle(v: string) { this.state.strokeStyle = v; }
  get lineWidth(): number { return this.state.lineWidth; }
  set lineWidth(v: number) { this.state.lineWidth = v; }
  get lineCap(): CanvasLineCap { return this.state.lineCap; }
  set lineCap(v: CanvasLineCap) { this.state.lineCap = v; }
  get font(): string { return this.state.font; }
  set font(v: string) { this.state.font = v; }
  get textAlign(): CanvasTextAlign { return this.state.textAlign; }
  set textAlign(v: CanvasTextAlign) { this.state.textAlign = v; }
  get globalAlpha(): number { return this.state.globalAlpha; }
  set globalAlpha(v: number) { this.state.globalAlpha = v; }

  save(): void {
    this.stack.push({ ...this.state, lineDash: [...this.state.lineDash] });
  }
  restore(): void {
    this.state = this.stack.pop() ?? this.state;
  }
  setTransform(a: number, b: number, c: number, d: number, e: number, f: number): void {
    this.state.transform = [a, b, c, d, e, f];
  }
  translate(x: number, y: number): void {
    this.state.transform = multiply(this.state.transform, [1, 0, 0, 1, x, y]);
  }
  setLineDash(dash: number[]): void {
    this.state.lineDash = [...dash];
  }

  beginPath(): void {
    this.path = new SvgPath();
  }
  moveTo(x: number, y: number): void { this.path.moveTo(x, y); }
  lineTo(x: number, y: number): void { this.path.lineTo(x, y); }
  bezierCurveTo(a: number, b: number, c: number, d: number, x: number, y: number): void { this.path.bezierCurveTo(a, b, c, d, x, y); }
  closePath(): void { this.path.closePath(); }
  rect(x: number, y: number, w: number, h: number): void { this.path.rect(x, y, w, h); }
  arc(cx: number, cy: number, r: number, s: number, e: number): void { this.path.arc(cx, cy, r, s, e); }
  ellipse(cx: number, cy: number, rx: number, ry: number, rot: number, s: number, e: number): void { this.path.ellipse(cx, cy, rx, ry, rot, s, e); }

  fill(path?: SvgPath): void {
    this.emitPath((path ?? this.path).data, true);
  }
  stroke(path?: SvgPath): void {
    this.emitPath((path ?? this.path).data, false);
  }
  clip(path?: SvgPath): void {
    const id = `c${++this.clips}`;
    const outer = this.state.clip ? ` clip-path="url(#${this.state.clip})"` : "";
    this.defs.push(`<clipPath id="${id}" clipPathUnits="userSpaceOnUse"${outer}><path d="${(path ?? this.path).data}"${this.transformAttr()}/></clipPath>`);
    this.state.clip = id;
  }
  fillRect(x: number, y: number, w: number, h: number): void {
    const p = new SvgPath();
    p.rect(x, y, w, h);
    this.emitPath(p.data, true);
  }
  strokeRect(x: number, y: number, w: number, h: number): void {
    const p = new SvgPath();
    p.rect(x, y, w, h);
    this.emitPath(p.data, false);
  }
  fillText(text: string, x: number, y: number): void {
    const [color, alpha] = svgColor(this.state.fillStyle);
    const anchor = this.state.textAlign === "center" ? "middle" : this.state.textAlign === "right" || this.state.textAlign === "end" ? "end" : "start";
    const opacity = alpha * this.state.globalAlpha;
    this.emit(`<text x="${num(x)}" y="${num(y)}" fill="${color}"${opacity < 1 ? ` fill-opacity="${num(opacity)}"` : ""}`
      + `${anchor !== "start" ? ` text-anchor="${anchor}"` : ""} style="font:${escapeXml(this.state.font)};white-space:pre"`
      + `${this.transformAttr()}>${escapeXml(text)}</text>`);
  }

  private transformAttr(): string {
    const m = this.state.transform;
    if (m.every((v, i) => v === IDENTITY[i])) return "";
    return ` transform="matrix(${m.map(num).join(" ")})"`;
  }

  private emitPath(d: string, fill: boolean): void {
    if (!d) return;
    const s = this.state;
    const [color, alpha] = svgColor(fill ? s.fillStyle : s.strokeStyle);
    const opacity = alpha * s.globalAlpha;
    let attrs = fill
      ? `fill="${color}"${opacity < 1 ? ` fill-opacity="${num(opacity)}"` : ""}`
      : `fill="none" stroke="${color}" stroke-width="${num(s.lineWidth)}"${opacity < 1 ? ` stroke-opacity="${num(opacity)}"` : ""}`
        + `${s.lineCap !== "butt" ? ` stroke-linecap="${s.lineCap}"` : ""}`
        + `${s.lineDash.length ? ` stroke-dasharray="${s.lineDash.map(num).join(" ")}"` : ""}`;
    if (fill && opacity === 0) attrs = 'fill="none"';
    this.emit(`<path d="${d}" ${attrs}${this.transformAttr()}/>`);
  }

  private emit(element: string): void {
    // Clips are in the page's coordinates, so a clipped element sits in an untransformed group.
    this.body.push(this.state.clip ? `<g clip-path="url(#${this.state.clip})">${element}</g>` : element);
  }

  /** The drawing as an SVG document `width` × `height` pixels. */
  svg(width: number, height: number): string {
    return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${num(width)}" height="${num(height)}" `
      + `viewBox="0 0 ${num(width)} ${num(height)}">\n<defs>${this.defs.join("")}</defs>\n${this.body.join("\n")}\n</svg>\n`;
  }
}
