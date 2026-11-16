// Board file format, ported from heddle/model.py in W1.
//
// For now this holds only the identifiers that must match the desktop app exactly, so a
// board saved by either app is recognised by the other. The W1 fixtures check
// FORMAT_VERSION against the Python core, so a format bump can't land in one app only.

/** Written to a board's "app" field. Loading never checks it (old names still open). */
export const APP_NAME = "Heddle";

/** Must equal model.FORMAT_VERSION in heddle/model.py. */
export const FORMAT_VERSION = 12;
