import { useState } from "react";
import { copyRoute, makeRoute } from "../core/model.ts";
import { casefold } from "../core/pystr.ts";
import type { BoardStore } from "../board/store.ts";
import { Dialog } from "./Dialog.tsx";
import { useDetailFields } from "./DetailFields.tsx";
import { TokenInput } from "./TokenInput.tsx";

/** Edit a route's own fields (heddle/route_dialog.py: Routes panel → Edit fields…). */
export function RouteDialog({ store, routeKey, steps, defaultName, onClose }: {
  store: BoardStore; routeKey: string[]; steps: string[]; defaultName: string; onClose: () => void;
}) {
  const saved = store.routeData(routeKey);
  const data = saved ? copyRoute(saved) : makeRoute({ key: routeKey });
  const [name, setName] = useState(data.name);
  const [inherit, setInherit] = useState(data.inherit);
  const details = useDetailFields(store, data, "route");
  const ok = () => {
    // makeRoute tidies the fields as the desktop's RouteData does (POV joins Characters).
    store.setRouteData(makeRoute({ ...details.values(), key: [...routeKey], name: name.trim(), inherit }));
    onClose();
  };
  return (
    <Dialog title="Edit route" onOk={ok} onCancel={onClose} wide>
      <p className="muted" title="The cards this route passes through, in order">{steps.join(" → ")}</p>
      <div className="field">
        <label htmlFor="route-name">Name</label>
        <input id="route-name" type="text" value={name} placeholder={defaultName} onChange={(e) => setName(e.target.value)} />
      </div>
      <TokenInput label="Tags" values={details.tags} onChange={details.setTags} suggestions={store.allValues("tags")} noun="tag"
                  onPending={(t) => details.setPending("tags", t)} />
      {details.fields}
      <div className="field">
        <span className="label">Inherit</span>
        <label title="Tags, characters, POV, locations and statuses of the route's cards are listed with its own. They follow the cards as you edit them; nothing is copied.">
          <input type="checkbox" checked={inherit} onChange={(e) => setInherit(e.target.checked)} /> Also show every strand its cards have
        </label>
      </div>
    </Dialog>
  );
}

/** Which character's thread to show (the desktop's Character Thread… question). The
 *  selected card's POV, or else its first character, is offered first. */
export function ThreadChooser({ store, onClose, onPick }: {
  store: BoardStore; onClose: () => void; onPick: (name: string) => void;
}) {
  const names = store.allValues("characters");
  const one = store.selected.size === 1 ? store.card([...store.selected][0]!) : undefined;
  const preferred = one ? one.pov || one.characters[0] || "" : "";
  const [name, setName] = useState(() => names.find((n) => casefold(n) === casefold(preferred)) ?? names[0] ?? "");
  return (
    <Dialog title="Character thread" okLabel="Show thread" onOk={() => onPick(name)} onCancel={onClose}>
      <div className="field">
        <label htmlFor="thread-name">Follow which character?</label>
        <select id="thread-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onPick(name); } }}>
          {names.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
    </Dialog>
  );
}
