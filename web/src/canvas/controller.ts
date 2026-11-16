// The board canvas: drawing on demand, pan and zoom, and editing with the mouse and
// keyboard (heddle/view.py, the scene's mouse and key handling, and CardItem's).
//
// Mouse: click selects (Ctrl+click adds or removes), dragging a card moves the selection,
// dragging empty canvas draws a selection box, Space+drag or the middle button pans,
// the wheel pans and Ctrl+wheel zooms. Dragging a card's ● handle connects it to the
// card you let go on, or makes a new connected card on empty canvas. Double-click adds
// a card (on empty canvas or in a group) or edits one.
//
// Things that need a dialog (editing a card or arrow, confirming a delete) go through
// the host callbacks, so this file never touches React.

import { boardExtent, portCenter, hasPort, CARD_WIDTH, type CardBox, type Rect } from "../board/metrics.ts";
import { NUDGE_FINE, NUDGE_STEP, GRID, type BoardStore, type BoardState } from "../board/store.ts";
import type { TextMeasurer } from "../board/text.ts";
import { Camera, ZOOM_STEP } from "./camera.ts";
import { drawBoard, type Hover } from "./draw.ts";
import { hitTest } from "./hit.ts";
import { LIGHT, withAlpha, type Theme } from "./theme.ts";

const CLICK_SLOP = 4; // px a press may move and still count as a click
const TOOLTIP_DELAY_MS = 600;
const NEW_CARD_MIN_DRAG = 40; // a handle dropped this far out on empty canvas makes a card
const NUDGE_SETTLE_MS = 500; // a burst of nudges closer together than this is one undo step

export interface CanvasHost {
  editCard(id: string, isNew: boolean): void;
  editArrows(ids: string[]): void;
  /** Ask before deleting several things; resolves true to go ahead. */
  confirm(message: string): Promise<boolean>;
  /** A short message for the status line ("nothing to reverse"). */
  notice(text: string): void;
  snapToGrid(): boolean;
}

type Listener = () => void;

type Gesture =
  | { kind: "click"; x: number; y: number; hit: Hover; moved: boolean }
  | { kind: "pan" }
  | { kind: "move"; x: number; y: number; card: string; roots: string[]; base: BoardState; moved: boolean }
  | { kind: "box"; x: number; y: number; add: boolean; before: Set<string>; beforeArrows: Set<string>; end: [number, number] }
  | { kind: "connect"; source: string; end: [number, number] };

export class BoardCanvas {
  readonly camera = new Camera();
  store: BoardStore | null = null;
  theme: Theme = LIGHT;
  private hover: Hover = {};
  private frame = 0;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly listeners = new Set<Listener>();
  private readonly pointers = new Map<number, { x: number; y: number }>();
  private gesture: Gesture | null = null;
  private pinch: { dist: number; mx: number; my: number } | null = null;
  private spaceHeld = false;
  private lastPointer: [number, number] | null = null;
  private tooltipTimer = 0;
  private nudgeTimer = 0;
  private unsubscribeStore: (() => void) | null = null;
  private readonly resizeObserver: ResizeObserver;
  private readonly cleanup: (() => void)[] = [];

  constructor(readonly canvas: HTMLCanvasElement, private readonly m: TextMeasurer,
              private readonly tooltip: HTMLElement, private readonly host: CanvasHost) {
    this.ctx = canvas.getContext("2d")!;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.on(canvas, "pointerdown", (e) => this.pointerDown(e as PointerEvent));
    this.on(canvas, "pointermove", (e) => this.pointerMove(e as PointerEvent));
    this.on(canvas, "pointerup", (e) => this.pointerUp(e as PointerEvent));
    this.on(canvas, "pointercancel", (e) => this.pointerUp(e as PointerEvent, true));
    this.on(canvas, "pointerleave", () => {
      this.lastPointer = null;
      if (!this.gesture) this.setHover({});
    });
    this.on(canvas, "dblclick", (e) => this.doubleClick(e as MouseEvent));
    this.on(canvas, "wheel", (e) => this.wheel(e as WheelEvent), { passive: false });
    this.on(canvas, "contextmenu", (e) => e.preventDefault());
    this.on(canvas, "keydown", (e) => this.keyDown(e as KeyboardEvent));
    // Space pans whenever the pointer is over the canvas, unless you're typing somewhere.
    this.on(window, "keydown", (e) => {
      const k = e as KeyboardEvent;
      if (k.code === "Space" && !typing(k) && this.lastPointer && !k.repeat) {
        this.spaceHeld = true;
        this.canvas.style.cursor = "grab";
        k.preventDefault();
      }
    });
    this.on(window, "keyup", (e) => {
      if ((e as KeyboardEvent).code === "Space" && this.spaceHeld) {
        this.spaceHeld = false;
        this.canvas.style.cursor = "";
      }
    });
    this.resize();
  }

  private on(target: EventTarget, type: string, fn: (e: Event) => void, opts?: AddEventListenerOptions): void {
    target.addEventListener(type, fn, opts);
    this.cleanup.push(() => target.removeEventListener(type, fn, opts));
  }

  destroy(): void {
    this.resizeObserver.disconnect();
    this.unsubscribeStore?.();
    for (const fn of this.cleanup) fn();
    cancelAnimationFrame(this.frame);
    clearTimeout(this.tooltipTimer);
    this.flushNudges();
  }

  /** Told after every pan, zoom or board change (the minimap and toolbar listen). */
  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  setStore(store: BoardStore | null): void {
    this.flushNudges();
    this.unsubscribeStore?.();
    this.store = store;
    this.hover = {};
    this.gesture = null;
    this.unsubscribeStore = store ? store.subscribe(() => this.changed()) : null;
    this.fit();
  }

  setTheme(theme: Theme): void {
    this.theme = theme;
    this.changed();
  }

  redraw(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.draw();
    });
  }

  private changed(): void {
    this.redraw();
    for (const fn of this.listeners) fn();
  }

  fit(): void {
    this.camera.fit(this.store ? boardExtent(this.store.boxes) : null);
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

  /** Where a new card goes from the keyboard: under the pointer, else mid-screen. */
  newCardPoint(): [number, number] {
    const [sx, sy] = this.lastPointer ?? [this.camera.width / 2, this.camera.height / 2];
    return this.camera.toScene(sx, sy);
  }

  /** Bring a card into view if it's off screen. */
  reveal(id: string): void {
    const b = this.store?.boxes.get(id);
    if (!b) return;
    const v = this.camera.visible();
    if (b.x < v.x || b.y < v.y || b.x + b.w > v.x + v.w || b.y + b.h > v.y + v.h) this.centerOn(b.x + b.w / 2, b.y + b.h / 2);
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
    else this.camera.centerOn(cx, cy);
    this.draw();
    this.changed();
  }

  private draw(): void {
    const dpr = window.devicePixelRatio || 1;
    const ctx = this.ctx;
    if (!this.store) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = this.theme.canvasBg;
      ctx.fillRect(0, 0, this.camera.width, this.camera.height);
      return;
    }
    const g = this.gesture;
    const lifted = g?.kind === "move" && g.moved ? this.liftedIds(g.roots) : undefined;
    drawBoard(ctx, { store: this.store, camera: this.camera, theme: this.theme, m: this.m, hover: this.hover, dpr, lifted });
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (g?.kind === "box") {
      const r = screenRect(g.x, g.y, g.end[0], g.end[1]);
      ctx.fillStyle = withAlpha("#4a7fc1", 40);
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.strokeStyle = "#4a7fc1";
      ctx.lineWidth = 1;
      ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w, r.h);
    } else if (g?.kind === "connect") {
      const src = this.store.boxes.get(g.source);
      if (src) {
        const [px, py] = this.camera.toScreen(...portCenter(src));
        ctx.strokeStyle = this.theme.selected;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(g.end[0], g.end[1]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
  }

  private liftedIds(roots: readonly string[]): Set<string> {
    const out = new Set<string>();
    for (const r of roots) {
      out.add(r);
      for (const d of this.store!.structure.descendants(r)) out.add(d);
    }
    return out;
  }

  private local(e: MouseEvent): [number, number] {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  private hitAt(sx: number, sy: number): Hover {
    if (!this.store) return {};
    const [x, y] = this.camera.toScene(sx, sy);
    return hitTest(this.store.boxes, this.store.arrows, this.store.state.display, x, y, this.camera.scale);
  }

  private setHover(h: Hover): void {
    const same = h.card === this.hover.card && h.part === this.hover.part && h.arrow === this.hover.arrow;
    if (same) return;
    this.hover = h;
    this.updateCursor();
    this.hideTooltip();
    this.redraw();
  }

  private updateCursor(): void {
    const h = this.hover;
    this.canvas.style.cursor = this.spaceHeld ? "grab"
      : h.part === "toggle" || h.part === "fold" ? "pointer"
        : h.part === "port" ? "crosshair" : h.card ? "move" : "";
  }

  // ----- pointer ---------------------------------------------------------------------

  private pointerDown(e: PointerEvent): void {
    const [x, y] = this.local(e);
    this.canvas.focus({ preventScroll: true });
    this.canvas.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x, y });
    this.hideTooltip();
    if (this.pointers.size === 2) {
      this.cancelGesture();
      this.pinch = this.pinchState();
      return;
    }
    if (!this.store) return;
    const touch = e.pointerType === "touch";
    if (e.button === 1 || (e.button === 0 && this.spaceHeld)) {
      if (e.button === 1) e.preventDefault();
      this.gesture = { kind: "pan" };
      this.canvas.style.cursor = "grabbing";
      return;
    }
    if (e.button !== 0) return;
    const hit = this.hitAt(x, y);
    const add = e.ctrlKey || e.metaKey;
    if (hit.part === "toggle" || hit.part === "fold") {
      this.gesture = { kind: "click", x, y, hit, moved: false };
      return;
    }
    if (hit.part === "port" && hit.card) {
      this.gesture = { kind: "connect", source: hit.card, end: [x, y] };
      return;
    }
    if (hit.card) {
      if (add) {
        this.store.toggleSelected(hit.card);
        this.gesture = null;
        return;
      }
      if (!this.store.selected.has(hit.card)) this.store.select([hit.card]);
      if (touch) { // a finger drag on a card pans (it moves cards only with a mouse or pen)
        this.gesture = { kind: "click", x, y, hit, moved: false };
        return;
      }
      this.gesture = { kind: "move", x, y, card: hit.card, roots: this.store.moveRoots(), base: this.store.state, moved: false };
      return;
    }
    if (hit.arrow) {
      if (add) this.store.toggleSelected(undefined, hit.arrow);
      else if (!this.store.selectedArrows.has(hit.arrow)) this.store.select([], [hit.arrow]);
      this.gesture = { kind: "click", x, y, hit, moved: false };
      return;
    }
    if (touch) {
      this.gesture = { kind: "click", x, y, hit, moved: false };
      return;
    }
    this.gesture = {
      kind: "box", x, y, add, end: [x, y],
      before: new Set(this.store.selected), beforeArrows: new Set(this.store.selectedArrows),
    };
  }

  private pinchState(): { dist: number; mx: number; my: number } {
    const [a, b] = [...this.pointers.values()];
    return { dist: Math.hypot(b!.x - a!.x, b!.y - a!.y), mx: (a!.x + b!.x) / 2, my: (a!.y + b!.y) / 2 };
  }

  private pointerMove(e: PointerEvent): void {
    const [x, y] = this.local(e);
    this.lastPointer = [x, y];
    const last = this.pointers.get(e.pointerId);
    if (!last) {
      const hit = this.hitAt(x, y);
      this.setHover(hit);
      this.scheduleTooltip(hit, e.clientX, e.clientY);
      return;
    }
    this.pointers.set(e.pointerId, { x, y });
    if (this.pinch && this.pointers.size === 2) {
      const now = this.pinchState();
      this.camera.panBy(now.mx - this.pinch.mx, now.my - this.pinch.my);
      if (this.pinch.dist > 0) this.camera.zoomAt(now.dist / this.pinch.dist, now.mx, now.my);
      this.pinch = now;
      this.changed();
      return;
    }
    const g = this.gesture;
    if (!g || !this.store) return;
    switch (g.kind) {
      case "pan":
        this.camera.panBy(x - last.x, y - last.y);
        this.changed();
        return;
      case "click":
        if (!g.moved && Math.hypot(x - g.x, y - g.y) > CLICK_SLOP) g.moved = true;
        if (g.moved) { // a drag that started as a click (touch, or on a control) pans
          this.camera.panBy(x - last.x, y - last.y);
          this.changed();
        }
        return;
      case "move": {
        if (!g.moved && Math.hypot(x - g.x, y - g.y) <= CLICK_SLOP) return;
        if (!g.moved) {
          g.moved = true;
          this.store.moving = true;
          // Make-room pushes become the dragged cards' own positions now.
          g.base = this.store.movedBy(g.roots, 0, 0);
        }
        const k = this.camera.scale;
        this.store.preview(this.store.movedBy(g.roots, (x - g.x) / k, (y - g.y) / k, g.base));
        return;
      }
      case "box":
        g.end = [x, y];
        this.applyBox(g);
        return;
      case "connect":
        g.end = [x, y];
        this.setHover(this.hitAt(x, y));
        this.redraw();
        return;
    }
  }

  private applyBox(g: Extract<Gesture, { kind: "box" }>): void {
    const store = this.store!;
    const [x1, y1] = this.camera.toScene(g.x, g.y);
    const [x2, y2] = this.camera.toScene(g.end[0], g.end[1]);
    const band: Rect = screenRect(x1, y1, x2, y2);
    const cards = [...store.boxes.values()].filter((b) => b.visible && rectsMeet(b, band)).map((b) => b.card.id);
    const arrows = store.arrows.filter((a) => a.path.points().some(([px, py]) => inRect(band, px, py))
      || (a.label !== null && rectsMeet(a.label, band))).map((a) => a.conn.id);
    if (g.add) store.select([...g.before, ...cards], [...g.beforeArrows, ...arrows]);
    else store.select(cards, arrows);
  }

  private pointerUp(e: PointerEvent, cancelled = false): void {
    this.pointers.delete(e.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
    if (this.pointers.size > 0) return;
    const g = this.gesture;
    this.gesture = null;
    this.updateCursor();
    const store = this.store;
    if (!g || !store) return;
    const [x, y] = this.local(e);
    if (cancelled) {
      if (g.kind === "move" && g.moved) {
        store.moving = false;
        store.preview(g.base);
      }
      this.redraw();
      return;
    }
    switch (g.kind) {
      case "click":
        if (g.moved) return;
        if (g.hit.card && g.hit.part === "toggle") store.toggleDetails(g.hit.card);
        else if (g.hit.card && g.hit.part === "fold") store.setCollapsed([g.hit.card], !store.card(g.hit.card)!.collapsed);
        return;
      case "move":
        store.moving = false;
        if (!g.moved) {
          // A plain click on a card in a bigger selection selects just that card.
          if (store.selected.size + store.selectedArrows.size > 1) store.select([g.card]);
          return;
        }
        if (this.host.snapToGrid()) store.preview(store.snappedState(g.roots));
        store.commit();
        return;
      case "box":
        if (Math.hypot(x - g.x, y - g.y) <= CLICK_SLOP && !g.add) store.clearSelection();
        this.redraw();
        return;
      case "connect":
        this.finishConnect(g.source, x, y);
        this.redraw();
        return;
      case "pan":
        return;
    }
  }

  private finishConnect(source: string, sx: number, sy: number): void {
    const store = this.store!;
    const hit = this.hitAt(sx, sy);
    const target = hit.card;
    if (target && target !== source) {
      if (!store.connect(source, target)) this.host.notice("Those cards are already connected that way.");
      return;
    }
    if (target) return; // let go on itself: a slip
    const src = store.boxes.get(source)!;
    const [px, py] = this.camera.toScreen(...portCenter(src));
    if (Math.hypot(sx - px, sy - py) < NEW_CARD_MIN_DRAG) return;
    // Empty canvas: a new card there, in the source's colour, already connected. Its
    // side facing the source touches the pointer.
    const [x, y] = this.camera.toScene(sx, sy);
    const left = x < portCenter(src)[0] ? x - CARD_WIDTH : x;
    const card = store.addCard(left + CARD_WIDTH / 2, y + 20 - src.closedH / 2, this.host.snapToGrid(), src.card.color);
    store.connectNew(source, card.id);
    this.host.editCard(card.id, true);
  }

  private doubleClick(e: MouseEvent): void {
    const store = this.store;
    if (!store || e.button !== 0) return;
    const [sx, sy] = this.local(e);
    const hit = this.hitAt(sx, sy);
    if (hit.part === "toggle" || hit.part === "fold" || hit.part === "port") return;
    if (hit.arrow) {
      this.host.editArrows([hit.arrow]);
      return;
    }
    const [x, y] = this.camera.toScene(sx, sy);
    const box = hit.card ? store.boxes.get(hit.card) : undefined;
    if (box && !(box.isGroup && y > box.y + box.headerH)) {
      this.host.editCard(box.card.id, false);
      return;
    }
    // Empty canvas, or the body of a group: a new card there.
    const card = store.addCard(x, y, this.host.snapToGrid(), undefined, box?.card.id);
    this.host.editCard(card.id, true);
  }

  /** Scroll pans (Shift: sideways); Ctrl+scroll zooms, as does a trackpad pinch. */
  private wheel(e: WheelEvent): void {
    e.preventDefault();
    const scale = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
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

  private cancelGesture(): void {
    const g = this.gesture;
    if (g?.kind === "move" && g.moved && this.store) {
      this.store.moving = false;
      this.store.preview(g.base);
    }
    this.gesture = null;
    this.redraw();
  }

  // ----- keyboard (while the canvas has focus) -------------------------------------------

  private keyDown(e: KeyboardEvent): void {
    const store = this.store;
    if (!store) return;
    const ctrl = e.ctrlKey || e.metaKey;
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (e.key === "Escape") {
      if (this.gesture) this.cancelGesture();
      else store.clearSelection();
      e.preventDefault();
    } else if (e.key in arrows && !ctrl && !e.altKey && store.selected.size) {
      const fine = e.shiftKey;
      const snap = this.host.snapToGrid() && !fine;
      const step = fine ? NUDGE_FINE : snap ? GRID : NUDGE_STEP;
      const [dx, dy] = arrows[e.key]!;
      this.nudge(dx * step, dy * step, snap);
      e.preventDefault();
    } else if ((e.key === "Delete" || e.key === "Backspace") && !ctrl) {
      e.preventDefault();
      void this.deleteSelection();
    } else if (e.key === "Enter" && store.selected.size + store.selectedArrows.size) {
      e.preventDefault();
      if (store.selected.size === 1) this.host.editCard([...store.selected][0]!, false);
      else if (!store.selected.size) this.host.editArrows([...store.selectedArrows]);
    } else if (ctrl && !e.shiftKey && e.code === "KeyA") {
      e.preventDefault();
      store.selectAll();
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyN") {
      e.preventDefault();
      const [x, y] = this.newCardPoint();
      const card = store.addCard(x, y, this.host.snapToGrid());
      this.host.editCard(card.id, true);
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyR" && store.selectedArrows.size) {
      e.preventDefault();
      const before = store.state.connections;
      store.reverseArrows(store.selectedArrows);
      if (store.state.connections === before || store.state.connections.every((c, i) => c === before[i])) {
        this.host.notice("Those arrows already have one going the other way: nothing to reverse.");
      }
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyD" && store.selected.size) {
      e.preventDefault();
      const ids = [...store.selected];
      store.setDetails(ids, !ids.every((id) => store.details.has(id)));
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyC" && store.selected.size) {
      e.preventDefault();
      const groups = [...store.selected].filter((id) => store.boxes.get(id)?.isGroup);
      if (groups.length) store.setCollapsed(groups, !groups.every((id) => store.card(id)!.collapsed));
    }
  }

  /** Arrow keys: a burst of nudges (a held key) is one undo step. */
  private nudge(dx: number, dy: number, snap: boolean): void {
    const store = this.store!;
    store.moving = true;
    store.nudgePreview(dx, dy, snap);
    clearTimeout(this.nudgeTimer);
    this.nudgeTimer = window.setTimeout(() => this.flushNudges(), NUDGE_SETTLE_MS);
  }

  private flushNudges(): void {
    if (!this.nudgeTimer) return;
    clearTimeout(this.nudgeTimer);
    this.nudgeTimer = 0;
    if (this.store) {
      this.store.moving = false;
      this.store.commit();
    }
  }

  async deleteSelection(): Promise<void> {
    const store = this.store;
    if (!store || !(store.selected.size + store.selectedArrows.size)) return;
    const what = store.describeSelection();
    if (what && !(await this.host.confirm(`Delete ${what}?\n\nArrows attached to deleted cards are removed too. You can undo this with Ctrl+Z.`))) return;
    store.removeSelection();
  }

  // ----- tooltips --------------------------------------------------------------------------

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
    const store = this.store;
    if (!store) return "";
    if (hit.arrow) return store.arrows.find((a) => a.conn.id === hit.arrow)?.tooltip ?? "";
    const box: CardBox | undefined = hit.card ? store.boxes.get(hit.card) : undefined;
    if (!box) return "";
    if (hit.part === "body") return box.tooltip;
    if (hit.part === "toggle") return box.detailsVisible ? "Hide details" : "Show details";
    if (hit.part === "fold") return box.card.collapsed ? "Expand group" : "Collapse group";
    if (hit.part === "port" && hasPort(box, store.state.display)) return "Drag to another card to connect them";
    return "";
  }

  private hideTooltip(): void {
    clearTimeout(this.tooltipTimer);
    this.tooltip.hidden = true;
  }
}

/** Is the key going into a text box (where Space and letters are typing)? */
export function typing(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
}

function screenRect(x1: number, y1: number, x2: number, y2: number): Rect {
  return { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
}

const inRect = (r: Rect, x: number, y: number) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
const rectsMeet = (a: Rect, b: Rect) => a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h;
