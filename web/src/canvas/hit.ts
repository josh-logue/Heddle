// What's under the pointer: the topmost card or group (cards above arrows above groups,
// the last drawn first), which part of it, or an arrow.

import type { Display } from "../core/model.ts";
import {
  PORT_RADIUS, RESIZE_GRIP, foldRect, hasPort, paintOrder, portCenter, toggleRect, type CardBox, type Rect,
} from "../board/metrics.ts";
import { hitArrow, type ArrowShape } from "../board/routing.ts";
import type { Hover } from "./draw.ts";

const inRect = (r: Rect, x: number, y: number, pad = 0) =>
  x >= r.x - pad && x <= r.x + r.w + pad && y >= r.y - pad && y <= r.y + r.h + pad;

function partOf(b: CardBox, x: number, y: number, display: Display): Hover["part"] {
  const lx = x - b.x;
  const ly = y - b.y;
  if (hasPort(b, display)) {
    const [px, py] = portCenter(b);
    if (Math.hypot(x - px, y - py) <= PORT_RADIUS + 3) return "port";
  }
  if (b.isGroup && inRect(foldRect(), lx, ly, 2)) return "fold";
  if (inRect(toggleRect(b), lx, ly, 3)) return "toggle";
  if (b.isGroup && !b.card.collapsed && lx >= b.w - RESIZE_GRIP && ly >= b.h - RESIZE_GRIP) return "resize";
  return "body";
}

export function hitTest(boxes: ReadonlyMap<string, CardBox>, arrows: readonly ArrowShape[], display: Display,
                        x: number, y: number, scale: number): Hover {
  const { groups, cards } = paintOrder(boxes);
  const onCard = (b: CardBox) => inRect(b, x, y) || (hasPort(b, display)
    && Math.hypot(x - portCenter(b)[0], y - portCenter(b)[1]) <= PORT_RADIUS + 3);
  for (let i = cards.length - 1; i >= 0; i--) {
    const b = cards[i]!;
    if (onCard(b)) return { card: b.card.id, part: partOf(b, x, y, display) };
  }
  const tolerance = Math.max(6, 6 / scale);
  for (let i = arrows.length - 1; i >= 0; i--) {
    if (hitArrow(arrows[i]!, [x, y], tolerance)) return { arrow: arrows[i]!.conn.id };
  }
  for (let i = groups.length - 1; i >= 0; i--) {
    const b = groups[i]!;
    if (inRect(b, x, y)) return { card: b.card.id, part: partOf(b, x, y, display) };
  }
  return {};
}
