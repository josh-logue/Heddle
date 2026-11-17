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

import { boardExtent, portCenter, hasPort, CARD_WIDTH, HEADER_HEIGHT, type CardBox, type Rect } from "../board/metrics.ts";
import { CARD_COLORS, type StrandKind } from "../core/model.ts";
import { NUDGE_FINE, NUDGE_STEP, GRID, type BoardStore, type BoardState } from "../board/store.ts";
import type { TextMeasurer } from "../board/text.ts";
import { Camera, ZOOM_STEP } from "./camera.ts";
import { drawBoard, type Hover } from "./draw.ts";
import { hitTest } from "./hit.ts";
import { LIGHT, darker, withAlpha, type Theme } from "./theme.ts";
import { buildMenu, type MenuItem } from "./menus.ts";
import { canPasteHere, readFragment, writeFragment } from "../platform/clipboard.ts";
import { matchesKey, type KeyProfile } from "../platform/host.ts";

/** What a strand dragged from the Strands panel carries (ui/panels/StrandsPanel.tsx). */
export const STRAND_MIME = "application/x-heddle-strand";

/** The strand being dragged from this page's Strands panel, if any. Safari (WebKit) doesn't
 *  show a drag's own data types to the drop target, so the board looks here too. */
export const strandDragging: { current: { kind: StrandKind; name: string } | null } = { current: null };
const CLICK_SLOP = 4; // px a press may move and still count as a click
const TOOLTIP_DELAY_MS = 600;
const NEW_CARD_MIN_DRAG = 40; // a handle dropped this far out on empty canvas makes a card
const NUDGE_SETTLE_MS = 500; // a burst of nudges closer together than this is one undo step
const FRAME_EDGE_HIT = 14; // this close to a group's frame counts as on its edge

export interface CanvasHost {
  editCard(id: string, isNew: boolean): void;
  editArrows(ids: string[]): void;
  /** Edit several selected cards at once. */
  editSeveral(): void;
  /** Ask before deleting several things; resolves true to go ahead. */
  confirm(message: string): Promise<boolean>;
  /** A short message for the status line ("nothing to reverse"). */
  notice(text: string): void;
  snapToGrid(): boolean;
  /** Show a right-click menu at a point on the page. */
  contextMenu(items: MenuItem[], clientX: number, clientY: number): void;
  /** Open the Path Reader at a card. */
  read(id: string): void;
  /** Ask which character's thread to show (T). */
  chooseThread(): void;
  /** Settings: the plain wheel zooms (and Ctrl+wheel scrolls). */
  wheelZooms(): boolean;
  /** The host's keys for Add card and Character thread (they differ in a browser). */
  keys(): KeyProfile;
}

type Listener = () => void;

type Gesture =
  | { kind: "click"; x: number; y: number; hit: Hover; moved: boolean }
  | { kind: "pan" }
  | { kind: "move"; x: number; y: number; card: string; roots: string[]; base: BoardState; moved: boolean; hint: string | null }
  | { kind: "resize"; group: string; offset: [number, number] }
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
  /** Connect to…: the dashed line follows the pointer until a click picks the target. */
  private linking: { source: string; end: [number, number] } | null = null;
  private suppressMenu = false;
  /** A strand being dragged in from the Strands panel: where it would land. */
  private strandDrag: { x: number; y: number } | null = null;
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
    // A strand dragged from the Strands panel (its kind and name come with the drop).
    const strandDrag = (e: DragEvent) => strandDragging.current !== null || Array.from(e.dataTransfer?.types ?? []).includes(STRAND_MIME);
    this.on(canvas, "dragover", (e) => {
      const d = e as DragEvent;
      if (!strandDrag(d) || !this.store) return;
      const [x, y] = this.camera.toScene(...this.local(d));
      const ok = this.store.strandDropTarget(x, y) !== null;
      if (ok) d.preventDefault();
      d.dataTransfer!.dropEffect = ok ? "copy" : "none";
      this.strandDrag = { x, y };
      this.redraw();
    });
    this.on(canvas, "dragleave", () => {
      this.strandDrag = null;
      this.redraw();
    });
    this.on(canvas, "drop", (e) => {
      const d = e as DragEvent;
      this.strandDrag = null;
      if (!strandDrag(d) || !this.store) return;
      d.preventDefault();
      try {
        const raw = d.dataTransfer?.getData(STRAND_MIME);
        const { kind, name } = raw ? JSON.parse(raw) as { kind: StrandKind; name: string } : strandDragging.current!;
        strandDragging.current = null;
        const [x, y] = this.camera.toScene(...this.local(d));
        const [, notice] = this.store.dropStrand(kind, name, x, y, this.host.snapToGrid());
        if (notice) this.host.notice(notice);
        this.canvas.focus({ preventScroll: true });
      } catch {
        // (not a strand after all: nothing to drop)
      }
      this.redraw();
    });
    this.on(canvas, "wheel", (e) => this.wheel(e as WheelEvent), { passive: false });
    this.on(canvas, "contextmenu", (e) => this.contextMenu(e as MouseEvent));
    // Copy, cut and paste reach the board while it has the keyboard (not a text box).
    const mine = () => document.activeElement === canvas;
    this.on(document, "copy", (e) => {
      if (mine() && this.copy(e as ClipboardEvent)) e.preventDefault();
    });
    this.on(document, "cut", (e) => {
      if (mine() && this.cut(e as ClipboardEvent)) e.preventDefault();
    });
    this.on(document, "paste", (e) => {
      if (mine() && this.paste(e as ClipboardEvent)) e.preventDefault();
    });
    this.on(canvas, "keydown", (e) => this.keyDown(e as KeyboardEvent));
    // Space pans whenever the pointer is over the canvas, unless you're typing somewhere
    // or the keyboard is in something that uses Space itself (the Path Reader: next).
    this.on(window, "keydown", (e) => {
      const k = e as KeyboardEvent;
      const usesSpace = (k.target as HTMLElement | null)?.closest?.("[data-uses-space]");
      if (k.code === "Space" && !typing(k) && !usesSpace && this.lastPointer && !k.repeat) {
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
    const link = g?.kind === "connect" ? { source: g.source, end: g.end, click: false }
      : this.linking ? { ...this.linking, click: true } : null;
    let dropTarget: string | undefined = g?.kind === "move" && g.moved ? g.hint ?? undefined : undefined;
    let ghost: { rect: Rect; color: string } | undefined;
    if (this.strandDrag) {
      const { x, y } = this.strandDrag;
      const target = this.store.strandDropTarget(x, y);
      if (target) dropTarget = target[1] ?? undefined;
      if (target && target[0] !== "card") { // where the strand card it makes would go
        ghost = { rect: { x: x - CARD_WIDTH / 2, y: y - 20, w: CARD_WIDTH, h: HEADER_HEIGHT },
          color: CARD_COLORS[this.store.state.cards.length % CARD_COLORS.length]! };
      }
    }
    if (link) {
      dropTarget = this.connectTarget(link.source, link.end[0], link.end[1], link.click) ?? undefined;
      if (!dropTarget && !link.click && this.canCreateAt(link.source, link.end[0], link.end[1])) {
        const [x, y] = this.camera.toScene(...link.end);
        ghost = { rect: this.newCardRect(link.source, x, y), color: this.store.card(link.source)!.color };
      }
    }
    drawBoard(ctx, { store: this.store, camera: this.camera, theme: this.theme, m: this.m, hover: this.hover, dpr, lifted, dropTarget, ghost });
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (g?.kind === "box") {
      const r = screenRect(g.x, g.y, g.end[0], g.end[1]);
      ctx.fillStyle = withAlpha("#4a7fc1", 40);
      ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.strokeStyle = "#4a7fc1";
      ctx.lineWidth = 1;
      ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w, r.h);
    } else if (link) {
      const src = this.store.boxes.get(link.source);
      if (src) {
        const [px, py] = this.camera.toScreen(...portCenter(src));
        ctx.strokeStyle = darker(src.card.color, 110); // the source card's colour, as on the desktop
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(link.end[0], link.end[1]);
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
        : h.part === "port" ? "crosshair" : h.part === "resize" ? "nwse-resize" : h.card ? "move" : "";
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
    if (this.linking) { // Connect to…: a click picks the target; anything else cancels
      const { source } = this.linking;
      this.linking = null;
      this.updateCursor();
      if (e.button === 0) this.finishConnect(source, x, y, false, true);
      this.suppressMenu = e.button === 2;
      this.redraw();
      return;
    }
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
    if (hit.part === "resize" && hit.card) {
      // Keep the grip under the pointer at the same offset while dragging.
      const b = this.store.boxes.get(hit.card)!;
      const [px, py] = this.camera.toScene(x, y);
      this.store.select([hit.card]);
      this.gesture = { kind: "resize", group: hit.card, offset: [b.x + b.w - px, b.y + b.h - py] };
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
      this.gesture = { kind: "move", x, y, card: hit.card, roots: this.store.moveRoots(), base: this.store.state, moved: false, hint: null };
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
      if (this.linking) {
        this.linking.end = [x, y];
        this.redraw();
      }
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
          this.store.beginMove(g.roots);
          // Make-room pushes become the dragged cards' own positions now.
          g.base = this.store.movedBy(g.roots, 0, 0);
        }
        const k = this.camera.scale;
        this.store.preview(this.store.movedBy(g.roots, (x - g.x) / k, (y - g.y) / k, g.base));
        g.hint = this.store.dropHint(g.roots, ...this.camera.toScene(x, y));
        return;
      }
      case "resize": {
        const b = this.store.boxes.get(g.group);
        if (!b) return;
        const [px, py] = this.camera.toScene(x, y);
        this.store.preview(this.store.resizedGroup(g.group, px - b.x + g.offset[0], py - b.y + g.offset[1]));
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
        store.endMove();
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
        if (!g.moved) {
          // A plain click on a card in a bigger selection selects just that card.
          if (store.selected.size + store.selectedArrows.size > 1) store.select([g.card]);
          return;
        }
        if (this.host.snapToGrid()) store.preview(store.snappedState(g.roots));
        // Into the group under the pointer (as framed during the drag), or out of its group.
        store.dropInto(g.roots, ...this.camera.toScene(x, y));
        store.endMove();
        store.commit();
        return;
      case "resize":
        store.commit();
        return;
      case "box":
        if (Math.hypot(x - g.x, y - g.y) <= CLICK_SLOP && !g.add) store.clearSelection();
        this.redraw();
        return;
      case "connect":
        this.finishConnect(g.source, x, y, e.ctrlKey || e.metaKey);
        this.redraw();
        return;
      case "pan":
        return;
    }
  }

  /** Start Connect to… from a card: the next click on another card connects them. */
  startConnect(source: string): void {
    if (!this.store?.boxes.has(source)) return;
    this.cancelGesture();
    const src = this.store.boxes.get(source)!;
    this.linking = { source, end: this.lastPointer ?? this.camera.toScreen(...portCenter(src)) };
    this.canvas.style.cursor = "crosshair";
    this.canvas.focus({ preventScroll: true });
    this.host.notice("Click the card to connect to (Esc cancels).");
    this.redraw();
  }

  get isLinking(): boolean {
    return this.linking !== null;
  }

  /** The card or group a drop or click at screen point (sx, sy) would connect `source`
   *  to. Dragging a handle onto its own group connects to the group (a last card) only
   *  on the group's header or frame edge; inside it is where a new card would go. */
  private connectTarget(source: string, sx: number, sy: number, click: boolean): string | null {
    const store = this.store!;
    const target = this.hitAt(sx, sy).card;
    if (!target || target === source) return null;
    if (!click && store.structure.isInside(source, target)) {
      const b = store.boxes.get(target)!;
      const [x, y] = this.camera.toScene(sx, sy);
      const onEdge = y - b.y <= b.headerH || x - b.x <= FRAME_EDGE_HIT || b.x + b.w - x <= FRAME_EDGE_HIT
        || b.y + b.h - y <= FRAME_EDGE_HIT;
      if (!onEdge) return null;
    }
    return target;
  }

  /** Would letting go of a handle drag here make a new card? On empty canvas (or empty
   *  space in a group), after a real drag rather than a slip. */
  private canCreateAt(source: string, sx: number, sy: number): boolean {
    const store = this.store!;
    const hit = this.hitAt(sx, sy);
    if (hit.card && !store.boxes.get(hit.card)?.isGroup) return false;
    const [px, py] = this.camera.toScreen(...portCenter(store.boxes.get(source)!));
    return Math.hypot(sx - px, sy - py) >= NEW_CARD_MIN_DRAG;
  }

  /** Where a card made by dropping at (x, y) goes: its side facing the source touches the
   *  pointer (so the arrow ends where it was dropped), centred on it vertically. */
  private newCardRect(source: string, x: number, y: number): Rect {
    const [w, h] = this.store!.newCardSize();
    const left = x < portCenter(this.store!.boxes.get(source)!)[0] ? x - w : x;
    return { x: left, y: y - h / 2, w, h };
  }

  private finishConnect(source: string, sx: number, sy: number, quick: boolean, click = false): void {
    const store = this.store!;
    const target = this.connectTarget(source, sx, sy, click);
    if (target) {
      if (!store.connect(source, target)) this.host.notice("Those cards are already connected that way.");
      return;
    }
    // Connect to… never makes cards: a click on empty canvas just cancels it.
    if (click || !this.canCreateAt(source, sx, sy)) return;
    // A new card there (in the group under it), in the source's colour, already
    // connected: one undo step. Ctrl+drop skips the editor.
    const [x, y] = this.camera.toScene(sx, sy);
    const rect = this.newCardRect(source, x, y);
    const group = store.groupAt(x, y) ?? undefined;
    const card = store.addCard(rect.x + CARD_WIDTH / 2, rect.y + 20, this.host.snapToGrid(), store.card(source)!.color, group);
    store.connectNew(source, card.id);
    if (quick) store.commit();
    else this.host.editCard(card.id, true);
  }

  /** Right-click: the menu for what's under the pointer. */
  private contextMenu(e: MouseEvent): void {
    e.preventDefault();
    if (this.suppressMenu) {
      this.suppressMenu = false;
      return;
    }
    const store = this.store;
    if (!store) return;
    const [sx, sy] = this.local(e);
    const [x, y] = this.camera.toScene(sx, sy);
    const items = buildMenu(store, this.hitAt(sx, sy), x, y, {
      editCard: (id) => this.host.editCard(id, false),
      editArrows: (ids) => this.host.editArrows(ids),
      editSeveral: () => this.host.editSeveral(),
      addCardAt: (cx, cy, group) => {
        const card = store.addCard(cx, cy, this.host.snapToGrid(), undefined, group);
        this.host.editCard(card.id, true);
      },
      startConnect: (id) => this.startConnect(id),
      copy: () => this.copy(),
      cut: () => this.cut(),
      pasteAt: (px, py) => this.paste(null, [px, py]),
      canPaste: canPasteHere,
      deleteSelection: () => void this.deleteSelection(),
      notice: (text) => this.host.notice(text),
      read: (id) => this.host.read(id),
      addCardKeys: this.host.keys().addCard.label,
    });
    this.host.contextMenu(items, e.clientX, e.clientY);
  }

  // ----- clipboard -------------------------------------------------------------------------

  copy(event?: ClipboardEvent): boolean {
    const fragment = this.store?.selectionFragment();
    if (!fragment) return false;
    writeFragment(fragment, event);
    const n = fragment.cards.length;
    this.host.notice(`Copied ${n} card${n !== 1 ? "s" : ""}`);
    return true;
  }

  cut(event?: ClipboardEvent): boolean {
    const fragment = this.store?.selectionFragment();
    if (!fragment) return false;
    writeFragment(fragment, event);
    this.store!.cut();
    return true;
  }

  /** Paste copied cards: at `at`, else at the pointer if it's over the board, else just
   *  beside the originals. */
  paste(event: ClipboardEvent | null, at?: [number, number]): boolean {
    const store = this.store;
    const fragment = readFragment(event ?? undefined);
    if (!store || !fragment) return false;
    const point = at ?? (this.lastPointer ? this.camera.toScene(...this.lastPointer) : null);
    store.paste(fragment, point);
    return true;
  }

  private doubleClick(e: MouseEvent): void {
    const store = this.store;
    if (!store || e.button !== 0) return;
    const [sx, sy] = this.local(e);
    const hit = this.hitAt(sx, sy);
    if (hit.part === "resize" && hit.card) {
      store.fitFrame(hit.card); // back to fitting snugly round its cards
      return;
    }
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
    if ((e.ctrlKey || e.metaKey) !== this.host.wheelZooms()) {
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
      this.store.endMove();
      this.store.preview(g.base);
    } else if (g?.kind === "resize" && this.store) {
      this.store.preview(this.store.history.current ?? this.store.state);
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
      if (this.linking) {
        this.linking = null;
        this.updateCursor();
        this.redraw();
      } else if (this.gesture) this.cancelGesture();
      else if (store.highlight) store.clearHighlight();
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
      else if (store.selected.size > 1) this.host.editSeveral();
      else this.host.editArrows([...store.selectedArrows]);
    } else if (ctrl && e.shiftKey && e.code === "KeyA") {
      e.preventDefault();
      const groups = [...store.selected].filter((id) => store.boxes.get(id)?.isGroup);
      if (groups.length) store.autoArrange(groups);
    } else if (ctrl && !e.shiftKey && e.code === "KeyD") {
      e.preventDefault(); // (the browser's bookmark key)
      store.duplicate();
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyL" && store.selected.size === 1) {
      e.preventDefault();
      this.startConnect([...store.selected][0]!);
    } else if (ctrl && !e.shiftKey && e.code === "KeyA") {
      e.preventDefault();
      store.selectAll();
    } else if (matchesKey(this.host.keys().addCard, e)) {
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
    } else if (!ctrl && !e.altKey && e.code === "KeyH") {
      e.preventDefault(); // H: paths before and after (again: clear); Shift+H: step the direction
      const notice = e.shiftKey ? store.cyclePathsMode() : store.togglePaths();
      if (notice) this.host.notice(notice);
    } else if (!ctrl && !e.altKey && !e.shiftKey && e.code === "KeyO" && store.state.display.story_tools) {
      e.preventDefault();
      const notice = store.toggleOutside();
      if (notice) this.host.notice(notice);
    } else if (matchesKey(this.host.keys().thread, e) && store.state.display.story_tools) {
      e.preventDefault(); // (Ctrl+T on the desktop: a browser keeps that one, so there it's T)
      this.host.chooseThread();
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

  /** Before undo or redo: a burst of nudges still settling is recorded first (so undo takes
   *  back the nudge, not the step before it), and a drag or resize under way is cancelled
   *  (its drop would otherwise land on the board undo just brought back). */
  settle(): void {
    const g = this.gesture;
    if (g?.kind === "move" || g?.kind === "resize") this.cancelGesture();
    this.flushNudges();
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
    if (hit.part === "resize") return "Drag to resize the frame; double-click to fit it to its cards";
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
