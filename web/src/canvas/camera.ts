// Pan and zoom (heddle/view.py): which part of the board is on screen, at what scale.
// Screen point = (scene point − origin) × scale.

import type { Rect } from "../board/metrics.ts";

export const MIN_SCALE = 0.05;
export const MAX_SCALE = 3;
export const ZOOM_STEP = 1.15; // per mouse-wheel notch
const FIT_MARGIN = 60;

export class Camera {
  scale = 1;
  ox = 0;
  oy = 0;
  /** Screen size in CSS pixels. */
  width = 1;
  height = 1;

  toScene(sx: number, sy: number): [number, number] {
    return [this.ox + sx / this.scale, this.oy + sy / this.scale];
  }

  toScreen(x: number, y: number): [number, number] {
    return [(x - this.ox) * this.scale, (y - this.oy) * this.scale];
  }

  /** The part of the board on screen. */
  visible(): Rect {
    return { x: this.ox, y: this.oy, w: this.width / this.scale, h: this.height / this.scale };
  }

  /** Zoom by `factor`, keeping the scene point under (sx, sy) where it is. */
  zoomAt(factor: number, sx = this.width / 2, sy = this.height / 2): void {
    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale * factor));
    if (next === this.scale) return;
    const [x, y] = this.toScene(sx, sy);
    this.scale = next;
    this.ox = x - sx / next;
    this.oy = y - sy / next;
  }

  /** Move the view so the board shifts by (dx, dy) screen pixels. */
  panBy(dx: number, dy: number): void {
    this.ox -= dx / this.scale;
    this.oy -= dy / this.scale;
  }

  centerOn(x: number, y: number): void {
    this.ox = x - this.width / 2 / this.scale;
    this.oy = y - this.height / 2 / this.scale;
  }

  /** Actual size, keeping the centre of the screen where it is. */
  resetZoom(): void {
    this.zoomAt(1 / this.scale);
  }

  /** Show the whole board (never zoomed in past 100%). */
  fit(rect: Rect | null): void {
    if (rect === null) {
      this.scale = 1;
      this.centerOn(0, 0);
      return;
    }
    const w = rect.w + 2 * FIT_MARGIN;
    const h = rect.h + 2 * FIT_MARGIN;
    this.scale = Math.max(MIN_SCALE, Math.min(1, this.width / w, this.height / h));
    this.centerOn(rect.x + rect.w / 2, rect.y + rect.h / 2);
  }
}
