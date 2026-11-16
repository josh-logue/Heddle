import { useEffect, useMemo, useState, type ReactNode } from "react";
import { routeKeyId, titleLabels, type CardData, type RouteData } from "../../core/model.ts";
import { casefold, strip } from "../../core/pystr.ts";
import {
  INHERITED_FIELDS, defaultTitle, isTruncated, keyCards, listRoutes, loopDetails, mergedFields, routeTitle,
  searchText, stepsText,
} from "../../core/routes.ts";
import type { BoardStore } from "../../board/store.ts";
import { graphOf, useSettled } from "./useSettled.ts";

export const OWNER = "routes"; // marks the board's highlight as this panel's
const REFRESH_DELAY_MS = 300; // re-list this long after the board settles
const FIELD_LABELS = new Map<string, string>(INHERITED_FIELDS);

interface Props {
  store: BoardStore;
  /** Select some cards and bring them into view. */
  onShow: (ids: string[]) => void;
  /** Open the route's field editor: its key, its steps and the name it has by default. */
  onEdit: (key: string[], steps: string[], defaultName: string) => void;
}

/** Routes (heddle/routes_panel.py): every route through the story, from a start to an end.
 *  Click a row to light the route up; expand it (▸) to see its cards and its own fields.
 *  Fields whose route no longer exists are listed under "Missing routes" until deleted. */
export function RoutesPanel({ store, onShow, onEdit }: Props) {
  const state = useSettled(store.state, REFRESH_DELAY_MS);
  const [needle, setNeedle] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const data = useMemo(() => {
    const graph = graphOf(store, state);
    const saved = new Map(state.routes.map((r) => [routeKeyId(r.key), r]));
    const listing = listRoutes(graph, saved);
    const cards = new Map<string, CardData>(state.cards.map((c) => [c.id, c]));
    const labels = titleLabels(state.cards);
    return { graph, saved, listing, cards, labels };
  }, [store, state]);

  useEffect(() => () => {
    if (store.highlightOwner === OWNER) store.clearHighlight();
  }, [store]);

  const { listing, cards, labels, saved } = data;
  const fold = casefold(strip(needle));
  const shows = (key: string[]) => !fold || searchText(key, cards, saved.get(routeKeyId(key)) ?? null, labels).includes(fold);

  const highlight = (key: string[]) => {
    const graph = store.storyGraph();
    const route = graph.routeForKey(key);
    if (!route) return;
    const title = routeTitle(route.key, cards, store.routeData(route.key), route.stops, labels);
    store.setHighlight(route.cards, graph.routeArrows(route), null, `Route: ${title}`, OWNER);
    onShow(route.cards.filter((id) => store.card(id)));
  };

  const toggle = (id: string) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const row = (key: string[], stops: readonly (readonly string[])[] | null, missing: boolean) => {
    const id = routeKeyId(key);
    const route = saved.get(id) ?? null;
    const open = expanded.has(id);
    const steps = stepsText(key, cards, stops, labels);
    const n = keyCards(key).length;
    const meta = [`${n} card${n === 1 ? "" : "s"}`];
    if (key.some((part) => part.includes("+"))) meta.push("↻");
    if (route?.inherit) meta.push("inherits");
    if (missing) meta.push("missing");
    return (
      <li key={id} className="route-row">
        <div className="route-header">
          <button type="button" className="icon fold" aria-expanded={open} title="Show or hide this route's cards and fields"
                  aria-label={open ? "Hide the route's cards and fields" : "Show the route's cards and fields"}
                  onClick={() => toggle(id)}>{open ? "▾" : "▸"}</button>
          <button type="button" className="row-button strong" disabled={missing} onClick={() => highlight(key)}
                  title={missing ? "This route no longer exists: an arrow or card on it was removed" : steps.join(" → ")}>
            {routeTitle(key, cards, route, stops, labels)}
          </button>
          <span className="muted route-meta">{meta.join(" · ")}</span>
        </div>
        {open && (
          <div className="route-body">
            <ol className="route-steps" title={loopDetails(key, cards, stops, labels).join("\n\n") || undefined}>
              {steps.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
            <RouteFields data={route} ids={keyCards(key)} cards={cards} />
            {missing ? (
              <div className="row">
                <button type="button" title="Forget this missing route's fields (undo with Ctrl+Z)"
                        onClick={() => store.deleteRouteData(key)}>Delete fields</button>
              </div>
            ) : (
              <>
                <label title="Also show every tag, character, POV, location and status its cards have (they follow the cards)">
                  <input type="checkbox" checked={route?.inherit ?? false} onChange={(e) => {
                    store.setRouteData({ ...(route ?? blankRoute(key)), key: [...key], inherit: e.target.checked });
                  }} /> Inherit card strands
                </label>
                <div className="row">
                  <button type="button" onClick={() => onEdit([...key], steps, defaultTitle(key, cards, stops, labels))}>Edit fields…</button>
                  {route && (
                    <button type="button" title="Remove this route's name, strands and notes (undo with Ctrl+Z)"
                            onClick={() => store.deleteRouteData(key)}>Clear fields</button>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </li>
    );
  };

  const n = listing.total;
  let text = `${n} route${n === 1 ? "" : "s"}`;
  if (isTruncated(listing)) text += ` (showing ${listing.routes.length})`;
  if (listing.missing.length) text += ` · ${listing.missing.length} missing`;
  const listed = listing.routes.filter((r) => shows(r.key));
  const missing = listing.missing.filter((d) => shows(d.key));

  return (
    <div className="panel routes-panel">
      <p className="panel-summary"><strong>
        {n === 0 && !listing.missing.length
          ? "No routes yet: connect cards with arrows, and each way from a start to an end is listed here."
          : text}
      </strong></p>
      <input type="search" placeholder="Filter routes by name, card or strand" aria-label="Filter routes"
             value={needle} onChange={(e) => setNeedle(e.target.value)} />
      <ul className="routes-list" aria-label="Routes">
        {listed.map((r) => row(r.key, r.stops, false))}
      </ul>
      {missing.length > 0 && (
        <>
          <h3 className="panel-heading" title="Routes with fields that no longer exist: an arrow or card on them was removed. Reconnect them, or delete their fields.">Missing routes</h3>
          <ul className="routes-list" aria-label="Missing routes">
            {missing.map((d) => row(d.key, null, true))}
          </ul>
        </>
      )}
      <p className="muted small-note">Click a route to light it up. Expand it (▸) to see its cards and give it its own fields. A loop counts as one stop.</p>
    </div>
  );
}

function blankRoute(key: string[]): RouteData {
  return { key, name: "", tags: [], characters: [], pov: "", locations: [], status: "", notes: "", inherit: false };
}

/** A route's own fields, and with "inherit" on, its cards' strands in muted text. */
function RouteFields({ data, ids, cards }: { data: RouteData | null; ids: string[]; cards: ReadonlyMap<string, CardData> }) {
  const lines: ReactNode[] = [];
  if (data && strip(data.name)) lines.push(<><strong>Name</strong>: {strip(data.name)}</>);
  for (const [name, view] of mergedFields(data, ids, cards)) {
    if (!view.own.length && !view.inherited.length) continue;
    lines.push(
      <>
        <strong>{FIELD_LABELS.get(name)}</strong>: {view.own.join(", ")}
        {view.inherited.length > 0 && <span className="muted">{view.own.length ? " " : ""}+ {view.inherited.join(", ")} (from cards)</span>}
      </>,
    );
  }
  if (data && strip(data.notes)) lines.push(<><strong>Notes</strong>: <span className="pre-wrap">{strip(data.notes)}</span></>);
  if (!lines.length) return <p className="muted">No fields set. Edit fields… to name or tag this route.</p>;
  return <div className="route-fields">{lines.map((l, i) => <div key={i}>{l}</div>)}</div>;
}
