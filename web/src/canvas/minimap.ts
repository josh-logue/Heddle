// The overview in the canvas's bottom-right corner (heddle/minimap.py): the board as
// coloured blocks with a box around the part on screen. Click to jump, drag the box to
// pan, scroll to zoom, double-click to fit.

import { boardExtent, paintOrder, type Rect } from "../board/metrics.ts";
import { ZOOM_STEP } from "./camera.ts";
import type { BoardCanvas } from "./controller.ts";
import { withAlpha } from "./theme.ts";

export const INSET = 6;
const PAD_FRACTION = 0.05;
const MIN_PAD = 60;
const MIN_BLOCK = 1.5;

type Transform = [s: number, dx: number, dy: number];

export class Minimap {
  private readonly ctx: CanvasRenderingContext2D;
  private drag: { offset: [number, number]; extent: Rect } | null = null;
  private readonly unsubscribe: () => void;
  private readonly cleanup: (() => void)[] = [];

  constructor(readonly canvas: HTMLCanvasElement, private readonly board: BoardCanvas) {
    this.ctx = canvas.getContext("2d")!;
    this.unsubscribe = board.subscribe(() => this.draw());
    const on = (type: string, fn: (e: Event) => void, opts?: AddEventListenerOptions) => {
      canvas.addEventListener(type, fn, opts);
      this.cleanup.push(() => canvas.removeEventListener(type, fn, opts));
    };
    on("pointerdown", (e) => this.down(e as PointerEvent));
    on("pointermove", (e) => this.move(e as PointerEvent));
    on("pointerup", () => (this.drag = null));
    on("dblclick", () => board.fit());
    on("wheel", (e) => {
      e.preventDefault();
      board.zoomBy(ZOOM_STEP ** (-(e as WheelEvent).deltaY / 100));
    }, { passive: false });
    this.draw();
  }

  destroy(): void {
    this.unsubscribe();
    for (const fn of this.cleanup) fn();
  }

  private cardsExtent(): Rect | null {
    const v = this.board.store;
    const b = v ? boardExtent(v.boxes) : null;
    if (!b) return null;
    const pad = Math.max(MIN_PAD, PAD_FRACTION * Math.max(b.w, b.h));
    return { x: b.x - pad, y: b.y - pad, w: b.w + 2 * pad, h: b.h + 2 * pad };
  }

  /** The cards, plus the on-screen area so its box never falls off the map. */
  private extent(): Rect {
    if (this.drag) return this.drag.extent; // moving the box mustn't rescale the map
    const visible = this.board.camera.visible();
    const world = this.cardsExtent();
    if (!world) return visible;
    const l = Math.min(world.x, visible.x);
    const t = Math.min(world.y, visible.y);
    return { x: l, y: t, w: Math.max(world.x + world.w, visible.x + visible.w) - l,
      h: Math.max(world.y + world.h, visible.y + visible.h) - t };
  }

  private transform(e: Rect): Transform {
    const w = this.canvas.clientWidth - 2 * INSET;
    const h = this.canvas.clientHeight - 2 * INSET;
    if (e.w <= 0 || e.h <= 0) return [1, INSET + w / 2, INSET + h / 2];
    const s = Math.min(w / e.w, h / e.h);
    return [s, INSET + (w - e.w * s) / 2 - e.x * s, INSET + (h - e.h * s) / 2 - e.y * s];
  }

  private toMap(r: Rect, [s, dx, dy]: Transform): Rect {
    let out = { x: r.x * s + dx, y: r.y * s + dy, w: r.w * s, h: r.h * s };
    if (out.w < MIN_BLOCK || out.h < MIN_BLOCK) { // tiny cards still show up
      const cx = out.x + out.w / 2;
      const cy = out.y + out.h / 2;
      const w = Math.max(out.w, MIN_BLOCK);
      const h = Math.max(out.h, MIN_BLOCK);
      out = { x: cx - w / 2, y: cy - h / 2, w, h };
    }
    return out;
  }

  private toScene(px: number, py: number): [number, number] {
    const [s, dx, dy] = this.transform(this.extent());
    return [(px - dx) / s, (py - dy) / s];
  }

  draw(): void {
    const dpr = window.devicePixelRatio || 1;
    const cw = this.canvas.clientWidth;
    const ch = this.canvas.clientHeight;
    if (!cw || !ch) return;
    if (this.canvas.width !== Math.round(cw * dpr)) this.canvas.width = Math.round(cw * dpr);
    if (this.canvas.height !== Math.round(ch * dpr)) this.canvas.height = Math.round(ch * dpr);
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    const t = this.board.theme;
    const viewer = this.board.store;
    if (!viewer) return;
    const xf = this.transform(this.extent());
    ctx.save();
    ctx.beginPath();
    ctx.rect(INSET, INSET, cw - 2 * INSET, ch - 2 * INSET);
    ctx.clip();
    const { groups, cards } = paintOrder(viewer.boxes);
    for (const b of [...groups, ...cards]) {
      const r = this.toMap(b, xf);
      if (b.isGroup) {
        ctx.fillStyle = withAlpha(b.card.color, 55);
        ctx.fillRect(r.x, r.y, r.w, r.h);
        ctx.strokeStyle = withAlpha(b.card.color, 190);
        ctx.lineWidth = 1;
        ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
      } else {
        ctx.fillStyle = b.card.color;
        ctx.fillRect(r.x, r.y, r.w, r.h);
      }
    }
    // The on-screen box.
    const box = this.toMap(this.board.camera.visible(), xf);
    ctx.fillStyle = withAlpha(t.cardText, 28);
    ctx.fillRect(box.x, box.y, box.w, box.h);
    ctx.strokeStyle = withAlpha(t.cardText, 170);
    ctx.lineWidth = 1.2;
    ctx.strokeRect(box.x, box.y, box.w, box.h);
    ctx.restore();
  }

  private local(e: PointerEvent): [number, number] {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  private down(e: PointerEvent): void {
    if (e.button !== 0) return;
    const [x, y] = this.toScene(...this.local(e));
    const v = this.board.camera.visible();
    const inside = x >= v.x && x <= v.x + v.w && y >= v.y && y <= v.y + v.h;
    // Grabbing the box drags it from where you grabbed it; elsewhere it jumps there.
    const offset: [number, number] = inside ? [v.x + v.w / 2 - x, v.y + v.h / 2 - y] : [0, 0];
    this.drag = { offset, extent: this.extent() };
    this.canvas.setPointerCapture(e.pointerId);
    this.board.centerOn(x + offset[0], y + offset[1]);
  }

  private move(e: PointerEvent): void {
    if (!this.drag) return;
    const [x, y] = this.toScene(...this.local(e));
    this.board.centerOn(x + this.drag.offset[0], y + this.drag.offset[1]);
  }
}
