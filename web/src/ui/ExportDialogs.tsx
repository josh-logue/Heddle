// File → Export: the story as text, the board as an image (heddle/export_dialogs.py). The
// choices are remembered per browser.

import { useState } from "react";
import { DEFAULT_TEXT_OPTIONS, DOCUMENT, OUTLINE, type TextOptions } from "../core/exportText.ts";
import { DEFAULT_IMAGE_OPTIONS, SCALES, type ImageOptions } from "../canvas/exportImage.ts";
import { readJson, writeJson } from "../platform/settings.ts";
import { Dialog } from "./Dialog.tsx";

export type TextScope = "board" | "selection" | "route";
export type ImageFormat = ImageOptions["format"] | "pdf";

function Radios<T extends string>({ name, value, choices, onChange }: {
  name: string; value: T; choices: [T, string, boolean][]; onChange: (v: T) => void;
}) {
  return (
    <div className="radios column" role="radiogroup" aria-label={name}>
      {choices.map(([v, label, enabled]) => (
        <label key={v} className={enabled ? undefined : "muted"}>
          <input type="radio" name={name} checked={value === v} disabled={!enabled} onChange={() => onChange(v)} /> {label}
        </label>
      ))}
    </div>
  );
}

export function loadTextOptions(): TextOptions {
  return { ...DEFAULT_TEXT_OPTIONS, ...readJson<Partial<TextOptions>>("exportText", {}) };
}

/** Scope (board / selection / route being read), layout and what to include. */
export function ExportTextDialog({ hasSelection, hasRoute, onClose, onExport }: {
  hasSelection: boolean; hasRoute: boolean; onClose: () => void; onExport: (scope: TextScope, options: TextOptions) => void;
}) {
  const [scope, setScope] = useState<TextScope>(hasRoute ? "route" : "board");
  const [opt, setOpt] = useState<TextOptions>(loadTextOptions);
  const flag = (key: "descriptions" | "details" | "notes" | "next_steps", label: string) => (
    <label key={key} className="block-check">
      <input type="checkbox" checked={opt[key]} onChange={(e) => setOpt({ ...opt, [key]: e.target.checked })} /> {label}
    </label>
  );
  return (
    <Dialog title="Export story as text" okLabel="Export…" onCancel={onClose} onOk={() => {
      writeJson("exportText", opt);
      onExport(scope, opt);
    }}>
      <div className="field">
        <span className="label">Export</span>
        <Radios name="Export" value={scope} onChange={setScope} choices={[
          ["board", "Whole board", true],
          ["selection", "Selected cards (and what's in selected groups)", hasSelection],
          ["route", "The route being read in the Path Reader", hasRoute],
        ]} />
      </div>
      <div className="field">
        <span className="label">Layout</span>
        <Radios name="Layout" value={opt.layout} onChange={(layout) => setOpt({ ...opt, layout })} choices={[
          [DOCUMENT, "Document: a heading per group and card, with its text", true],
          [OUTLINE, "Outline: nested bullet points", true],
        ]} />
      </div>
      <div className="field">
        <span className="label">Include</span>
        <div>
          {flag("descriptions", "Descriptions")}
          {flag("details", "Details (POV, characters, locations, status, tags)")}
          {flag("notes", "Notes")}
          {flag("next_steps", "Where each card leads (branches and arrow labels)")}
        </div>
      </div>
      <p className="muted small-note">Cards are listed in story order, along the arrows. Saved as Markdown (.md), which reads fine as plain text too.</p>
    </Dialog>
  );
}

export function loadImageOptions(): ImageOptions & { format: ImageFormat } {
  const saved = readJson<Partial<ImageOptions & { format: ImageFormat }>>("exportImage", {});
  const opts = { ...DEFAULT_IMAGE_OPTIONS, ...saved, selectionOnly: false };
  if (!(SCALES as readonly number[]).includes(opts.scale)) opts.scale = DEFAULT_IMAGE_OPTIONS.scale;
  return opts;
}

/** Scope, format, PNG scale, background, theme, and whether to keep the fading. */
/** `pdfByPrint`: a browser makes a PDF through its Print dialog; the desktop saves one. */
export function ExportImageDialog({ hasSelection, pdfByPrint = true, onClose, onExport }: {
  hasSelection: boolean; pdfByPrint?: boolean; onClose: () => void; onExport: (options: ImageOptions, format: ImageFormat) => void;
}) {
  const [opt, setOpt] = useState(loadImageOptions);
  const [format, setFormat] = useState<ImageFormat>(opt.format);
  const flag = (key: "transparent" | "light" | "asShown", label: string) => (
    <label key={key} className="block-check">
      <input type="checkbox" checked={opt[key]} onChange={(e) => setOpt({ ...opt, [key]: e.target.checked })} /> {label}
    </label>
  );
  return (
    <Dialog title="Export board as image" okLabel={format === "pdf" && pdfByPrint ? "Print…" : "Export…"} onCancel={onClose} onOk={() => {
      writeJson("exportImage", { ...opt, format, selectionOnly: false });
      onExport({ ...opt, format: format === "pdf" ? "svg" : format }, format);
    }}>
      <div className="field">
        <span className="label">Export</span>
        <Radios name="Export" value={opt.selectionOnly ? "selection" : "board"} onChange={(v) => setOpt({ ...opt, selectionOnly: v === "selection" })}
                choices={[["board", "Whole board", true], ["selection", "Selected cards (and what's in selected groups)", hasSelection]]} />
      </div>
      <div className="field">
        <span className="label">Format</span>
        <Radios name="Format" value={format} onChange={setFormat} choices={[
          ["png", "PNG image", true],
          ["svg", "SVG drawing (sharp at any size)", true],
          ["pdf", pdfByPrint ? "PDF: opens the browser's Print, then choose Save as PDF" : "PDF document (one page, sharp at any size)", true],
        ]} />
      </div>
      <div className="field">
        <label htmlFor="png-scale">PNG scale</label>
        <select id="png-scale" value={opt.scale} disabled={format !== "png"} onChange={(e) => setOpt({ ...opt, scale: Number(e.target.value) })}>
          <option value={1}>1× (screen size)</option>
          <option value={2}>2× (sharp)</option>
          <option value={3}>3× (print)</option>
        </select>
      </div>
      <div className="field">
        <span className="label">Look</span>
        <div>
          {flag("transparent", "Transparent background (else the canvas colour, without the grid)")}
          {flag("light", "Use the light theme (good for printing)")}
          {flag("asShown", "Keep the filter's and highlight's fading")}
        </div>
      </div>
      <p className="muted small-note">Handles, toggles and the selection aren't drawn. Very large boards are made smaller to fit the browser's limits for a PNG; SVG and PDF have none.</p>
    </Dialog>
  );
}
