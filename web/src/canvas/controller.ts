// The board canvas: drawing on demand, pan and zoom (wheel, drag, pinch), hover effects
// and tooltips, and the clicks the viewer supports (fold a group, show details).

import type { BoardViewer } from "../board/viewer.ts";
import type { TextMeasurer } from "../board/text.ts";
import { boardExtent } from "../board/metrics.ts";
import { Camera, ZOOM_STEP } from "./camera.ts";
import { drawBoard, type Hover } from "./draw.ts";
import { hitTest } from "./hit.ts";
import { LIGHT, type Theme } from "./theme.ts";

const CLICK_SLOP = 4; // px a press may move and still count as a click
const TOOLTIP_DELAY_MS = 600;

type Listener = () => void;

export class BoardCanvas {
  readonly camera = new Camera();
  viewer: BoardViewer | null = null;
  theme: Theme = LIGHT;
  private hover: Hover = {};
  private frame = 0;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly listeners = new Set<Listener>();
  private readonly pointers = new Map<number, { x: number; y: number }>();
  private press: { x: number; y: number; hit: Hover; moved: boolean } | null = null;
  private pinch: { dist: number; mx: number; my: number } | null = null;
  private tooltipTimer = 0;
  private readonly resizeObserver: ResizeObserver;
  private readonly cleanup: (() => void)[] = [];

  constructor(readonly canvas: HTMLCanvasElement, private readonly m: TextMeasurer,
              private readonly tooltip: HTMLElement) {
    this.ctx = canvas.getContext("2d")!;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.on(canvas, "pointerdown", (e) => this.pointerDown(e as PointerEvent));
    this.on(canvas, "pointermove", (e) => this.pointerMove(e as PointerEvent));
    this.on(canvas, "pointerup", (e) => this.pointerUp(e as PointerEvent));
    this.on(canvas, "pointercancel", (e) => this.pointerUp(e as PointerEvent, true));
    this.on(canvas, "pointerleave", () => this.setHover({}));
    this.on(canvas, "wheel", (e) => this.wheel(e as WheelEvent), { passive: false });
    this.on(canvas, "contextmenu", (e) => e.preventDefault());
    this.resize();
  }

  private on(target: EventTarget, type: string, fn: (e: Event) => void, opts?: AddEventListenerOptions): void {
    target.addEventListener(type, fn, opts);
    this.cleanup.push(() => target.removeEventListener(type, fn, opts));
  }

  destroy(): void {
    this.resizeObserver.disconnect();
    for (const fn of this.cleanup) fn();
    cancelAnimationFrame(this.frame);
    clearTimeout(this.tooltipTimer);
  }

  /** Told after every pan, zoom or board change (the minimap and zoom readout listen). */
  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  setViewer(viewer: BoardViewer | null): void {
    this.viewer = viewer;
    this.hover = {};
    this.fit();
  }

  setTheme(theme: Theme): void {
    this.theme = theme;
    this.redraw();
  }

  /** The board changed (folded, details shown): draw it again. */
  redraw(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
    });
  }

  /** The board changed (folded, details shown): draw it, and tell the minimap. */
  boardChanged(): void {
    this.changed();
  }

  private changed(): void {
    this.redraw();
    for (const fn of this.listeners) fn();
  }

  fit(): void {
    this.camera.fit(this.viewer ? boardExtent(this.viewer.boxes) : null);
    this.changed();
  }

  resetZoom(): void {
    this.camera.resetZoom();
    this.changed();
  }

  zoomBy(factor: number, sx?: number, sy?: number): void {
    this.camera.zoomAt(factor, sx, sy);
    this.changed();
  }

  centerOn(x: number, y: number): void {
    this.camera.centerOn(x, y);
    this.changed();
  }

  private resize(): void {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const first = this.camera.width <= 1;
    const [cx, cy] = this.camera.toScene(this.camera.width / 2, this.camera.height / 2);
    this.camera.width = Math.max(1, rect.width);
    this.camera.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.camera.width * dpr);
    this.canvas.height = Math.round(this.camera.height * dpr);
    if (first) this.fit();
    else this.camera.centerOn(cx, cy); // keep what was in the middle in the middle
    this.draw();
    this.changed();
  }

  private draw(): void {
    const dpr = window.devicePixelRatio || 1;
    const ctx = this.ctx;
    if (!this.viewer) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = this.theme.canvasBg;
      ctx.fillRect(0, 0, this.camera.width, this.camera.height);
      return;
    }
    drawBoard(ctx, { viewer: this.viewer, camera: this.camera, theme: this.theme, m: this.m, hover: this.hover, dpr });
  }

  private local(e: PointerEvent | WheelEvent): [number, number] {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  private hitAt(sx: number, sy: number): Hover {
    if (!this.viewer) return {};
    const [x, y] = this.camera.toScene(sx, sy);
    return hitTest(this.viewer.boxes, this.viewer.arrows, this.viewer.board.display, x, y, this.camera.scale);
  }

  private setHover(h: Hover): void {
    const same = h.card === this.hover.card && h.part === this.hover.part && h.arrow === this.hover.arrow;
    if (same) return;
    this.hover = h;
    this.canvas.style.cursor = h.part === "toggle" || h.part === "fold" ? "pointer" : "";
    this.hideTooltip();
    this.redraw();
  }

  private pointerDown(e: PointerEvent): void {
    const [x, y] = this.local(e);
    this.canvas.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x, y });
    this.hideTooltip();
    if (this.pointers.size === 2) {
      this.press = null; // a second finger: pinch, not a click
      this.pinch = this.pinchState();
      return;
    }
    if (e.button === 0 || e.button === 1 || e.pointerType !== "mouse") {
      this.press = { x, y, hit: this.hitAt(x, y), moved: false };
      if (e.button === 1) e.preventDefault(); // no autoscroll
    }
  }

  private pinchState(): { dist: number; mx: number; my: number } {
    const [a, b] = [...this.pointers.values()];
    return { dist: Math.hypot(b!.x - a!.x, b!.y - a!.y), mx: (a!.x + b!.x) / 2, my: (a!.y + b!.y) / 2 };
  }

  private pointerMove(e: PointerEvent): void {
    const [x, y] = this.local(e);
    const last = this.pointers.get(e.pointerId);
    if (last) {
      this.pointers.set(e.pointerId, { x, y });
      if (this.pinch && this.pointers.size === 2) {
        const now = this.pinchState();
        this.camera.panBy(now.mx - this.pinch.mx, now.my - this.pinch.my);
        if (this.pinch.dist > 0) this.camera.zoomAt(now.dist / this.pinch.dist, now.mx, now.my);
        this.pinch = now;
        this.changed();
        return;
      }
      if (this.press) {
        if (!this.press.moved && Math.hypot(x - this.press.x, y - this.press.y) > CLICK_SLOP) {
          this.press.moved = true;
          this.canvas.style.cursor = "grabbing";
        }
        if (this.press.moved) {
          this.camera.panBy(x - last.x, y - last.y); // viewing: any drag pans the board
          this.changed();
        }
      }
      return;
    }
    const hit = this.hitAt(x, y);
    this.setHover(hit);
    this.scheduleTooltip(hit, e.clientX, e.clientY);
  }

  private pointerUp(e: PointerEvent, cancelled = false): void {
    this.pointers.delete(e.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
    const press = this.press;
    if (this.pointers.size === 0) this.press = null;
    this.canvas.style.cursor = "";
    if (!press || press.moved || cancelled || !this.viewer) return;
    const { hit } = press;
    if (hit.card && hit.part === "toggle") this.viewer.toggleDetails(hit.card);
    else if (hit.card && hit.part === "fold") {
      const box = this.viewer.boxes.get(hit.card)!;
      this.viewer.setCollapsed(hit.card, !box.card.collapsed);
    } else return;
    this.changed();
  }

  /** Scroll pans (Shift: sideways); Ctrl+scroll zooms, as does a trackpad pinch (which
   *  the browser sends as Ctrl+wheel). */
  private wheel(e: WheelEvent): void {
    e.preventDefault();
    const scale = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1; // lines, pages
    if (e.ctrlKey || e.metaKey) {
      const [x, y] = this.local(e);
      this.zoomBy(ZOOM_STEP ** (-(e.deltaY * scale) / 100), x, y);
      return;
    }
    let dx = -e.deltaX * scale;
    let dy = -e.deltaY * scale;
    if (e.shiftKey && !dx) [dx, dy] = [dy, 0];
    this.camera.panBy(dx, dy);
    this.changed();
  }

  private scheduleTooltip(hit: Hover, cx: number, cy: number): void {
    clearTimeout(this.tooltipTimer);
    const text = this.tooltipFor(hit);
    if (!text) {
      this.hideTooltip();
      return;
    }
    this.tooltipTimer = window.setTimeout(() => {
      this.tooltip.textContent = text;
      this.tooltip.hidden = false;
      const host = this.canvas.getBoundingClientRect();
      const w = this.tooltip.offsetWidth;
      const left = Math.min(cx - host.left + 12, host.width - w - 8);
      this.tooltip.style.left = `${Math.max(8, left)}px`;
      this.tooltip.style.top = `${cy - host.top + 18}px`;
    }, TOOLTIP_DELAY_MS);
  }

  private tooltipFor(hit: Hover): string {
    if (!this.viewer) return "";
    if (hit.arrow) return this.viewer.arrows.find((a) => a.conn.id === hit.arrow)?.tooltip ?? "";
    if (hit.card && hit.part === "body") return this.viewer.boxes.get(hit.card)?.tooltip ?? "";
    if (hit.part === "toggle") return this.viewer.boxes.get(hit.card!)?.detailsVisible ? "Hide details" : "Show details";
    if (hit.part === "fold") return this.viewer.boxes.get(hit.card!)?.card.collapsed ? "Expand group" : "Collapse group";
    return "";
  }

  private hideTooltip(): void {
    clearTimeout(this.tooltipTimer);
    this.tooltip.hidden = true;
  }
}
