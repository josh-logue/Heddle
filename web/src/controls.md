<!--
The web version's controls, written once. The Help dialog (F1, or ? in the toolbar) shows
this file, and the README's "Web version keys" section is generated from it:
  cd web; npm run help
Format: "## Section" headings, then one "- **Action**: how" line per entry. A heading or
entry marked [browser] or [desktop] ("- **Action** [desktop]: how") is shown only in that
app; the README shows the browser's.
On a Mac, Cmd works wherever Ctrl is written.
-->

## Cards

- **Add card** [browser]: Double-click empty canvas, right-click → Add card here, the toolbar's *Add card*, or N with the board focused. Cancelling the editor for a new card removes it again
- **Add card** [desktop]: Double-click empty canvas, right-click → Add card here, the toolbar's *Add card*, or Ctrl+Shift+N. Cancelling the editor for a new card removes it again
- **Edit card**: Double-click it, or select it and press Enter
- **Card panel**: Panels → Card (Ctrl+Shift+E) shows the selected card's title, description and details beside the board. Type and pause: there's no OK, each save is one undo step. *More…* opens the editor (colour, type, a group's cards); with several cards selected it offers to edit them together
- **Edit several cards**: Select them, then Enter, Ctrl+E or right-click → Edit N selected cards…: colour, add or remove tags, characters and locations, status; anything left alone stays as it is
- **Move**: Drag a card (a group brings its cards along); drag on empty canvas to box-select; Ctrl+click adds to or takes from the selection
- **Nudge**: Arrow keys move the selection 10 px (Shift: 1 px); holding a key is one undo step
- **Snap to grid**: View → Snap cards to the grid (also in Settings), off by default: cards land on the 25 px grid when you drop or nudge them
- **Copy / cut / paste / duplicate** [browser]: Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+D. Groups bring their cards; arrows come along when both ends are copied. Paste goes to the mouse pointer (onto a group to add to it) and works between browser tabs; Ctrl+D places the copy beside the original
- **Copy / cut / paste / duplicate** [desktop]: Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+D. Groups bring their cards; arrows come along when both ends are copied. Paste goes to the mouse pointer (onto a group to add to it) and works between windows; Ctrl+D places the copy beside the original
- **Delete**: Del (or Backspace); deleting several things at once, or a group with its cards, asks first
- **Card keys** [browser]: With the board focused: **L** Connect to…, **D** show or hide details, **C** collapse or expand group, **H** highlight paths, **Shift+H** before / after, **O** not part of the story, **T** character thread, **R** reverse arrows, **Shift+C** collapse or expand all groups, **Shift+D** show or hide all details, **Ctrl+Shift+A** auto-arrange group. Right-click menus show each item's key
- **Card keys** [desktop]: With the board focused: **L** Connect to…, **D** show or hide details, **C** collapse or expand group, **H** highlight paths, **Shift+H** before / after, **O** not part of the story, **Ctrl+T** character thread, **R** reverse arrows, **Shift+C** collapse or expand all groups, **Shift+D** show or hide all details, **Ctrl+Shift+A** auto-arrange group. Right-click menus show each item's key
- **Which keys act on the board**: Plain letters, Del and Ctrl+A/C/X/V/D act on the board only while it has the keyboard (click the canvas), so typing in a panel or dialog never touches your cards
- **Show/hide card details**: Click ▸ on the card's header, or select cards and press D; View → Show every card's details (Shift+D). Opening details makes room: cards they would cover move down, and back when the details close. Making room isn't an edit
- **Tags / characters / locations**: In the editor, type and press Enter (the board's strands are suggested); × removes one
- **Custom colours**: In the card editor, + adds a colour to this board's palette; × on a custom swatch takes it off again while nothing else uses it
- **POV**: In the editor's details, pick or type the point-of-view character; they're added to Characters. Removing their chip clears the POV
- **Board options**: View → Board options… lists every option saved with the board (card face, connection handles, arrow labels, grid, arrow routing, story tools, highlight paths of selection); OK is one undo step
- **Not part of the story**: Tick it in the editor, right-click → Not part of the story, or press O, to leave a card (or a group and everything in it) out of story checks, routes, introductions and threads. It's drawn with a dashed outline

## Connections

- **Connect cards**: Drag from the round handle on a card's right edge onto another card, or press L (right-click → Connect to…) and click the target; Esc cancels
- **Add a connected card**: Drag a card's handle onto empty canvas: dropping makes a new card there with an arrow from the first, and opens its editor (Ctrl+drop skips the editor). One undo step
- **Edit an arrow**: Double-click it, or select it and press Enter: label, line style and colour. Select several arrows to change their style or colour together. Right-click an arrow for quick Line style and Color menus
- **Reverse / delete an arrow**: Select arrows and press R to reverse them, or Del to delete them

## Groups

- **Make a group**: In the card editor set Type → Group and tick its cards; or drag cards into a group's frame (drag them out to take them out). The group a drop would go into is outlined while you drag
- **Add a card to a group**: Double-click empty space inside it, or right-click it → Add card here
- **Resize a group**: Drag its bottom-right corner; double-click the corner to fit it to its cards again
- **Auto-arrange a group**: Group editor → Save & auto-arrange, right-click → Auto-arrange cards, or Ctrl+Shift+A. Options on the group's right-click menu and in its editor: rows by colour, top to bottom, unconnected cards in a grid, wrap rows after N steps
- **First / last cards of a group**: Connect a group to a card inside it to mark a first card, or a card inside to its own group to mark a last card
- **Ungroup or delete**: Right-click a group: Remove from group, Ungroup (keep cards), Delete group (keep cards), Delete group and its cards
- **Collapse a group**: Click the − at the left of its title bar (+ expands it), press C, or View → Collapse every group (Shift+C). A collapsed group shows how many cards it holds; arrows to hidden cards meet it, several drawn as one marked ×N. Saved with the board and undoable

## Story

- **Highlight paths**: Select a card and press H (or right-click → Highlight paths): what can come before and after it lights up and the rest fades. H or Esc clears; Shift+H switches between before and after, only what leads here and only what follows. View → Highlight paths of selection does it for whichever card you select
- **Read a path**: Right-click a card → Read from here (or Ctrl+Shift+R): the Path Reader shows the card's text and the ways on. → / Space / Enter follows a single arrow; at a branch press 1–9 or click a way on. ← / Backspace goes back along the route you took. Closing the panel ends the reading
- **Character thread** [browser]: T (View → Character thread…), right-click a card → Character thread, *Show thread* in the Strands panel, or right-click a character in the Filter panel: every card featuring the character lights up, numbered in story order and joined by a dashed line. Esc clears
- **Character thread** [desktop]: Ctrl+T (View → Character thread…), right-click a card → Character thread, *Show thread* in the Strands panel, or right-click a character in the Filter panel: every card featuring the character lights up, numbered in story order and joined by a dashed line. Esc clears
- **First appearances**: A card *introduces* a character when it features them and no card on any route leading to it does. Those cards show a ★, an Introduces line in their details, and the Filter panel's Introduces category finds them
- **Routes**: Panels → Routes (Ctrl+Shift+O) lists every route from a start to an end. Click one to light it up; expand it (▸) to see its cards, give it a name, strands and notes (Edit fields…), or have it inherit its cards' strands. Fields whose route was broken are kept under Missing routes
- **Story checks**: Panels → Story Checks (Ctrl+Shift+K): dead ends, several starts in one chain, loops, cards with no arrows, starts, endings and how many routes there are, for the board or one group. Click a result to find and highlight its cards. Mark deliberate endings with the tag or status *Ending* (changeable in the panel)

## Finding

- **Search**: Ctrl+F: searches titles, descriptions, notes and strands; Enter / F3 next, Shift+Enter / Shift+F3 previous, Esc leaves the box. A collapsed group counts the matches folded inside it
- **Go to card**: Ctrl+P (Edit → Go to card…): type part of a title and press Enter to jump to it
- **Replace**: Ctrl+H (Edit → Replace…) replaces text in titles, descriptions and notes, on every card or the selected ones; one undo step
- **Card list**: Panels → Card List (Ctrl+Shift+L): every card as a tree of its groups, in story order, top to bottom or A–Z, with a find box. Click a card to select it; Enter or a double-click opens a collapsed group to reach it
- **Filter cards**: Panels → Filter (Ctrl+L): tick tags, colours, characters, POV, introductions, locations or statuses and the other cards fade. Ticks in one category match any of them (or all, with *match all*); separate categories must all match
- **Strands**: Panels → Strands (Ctrl+Shift+B): every tag, character, location and status, how much each is used, and its description and fields. Drag a strand onto a card to add it, onto a group or blank canvas for a strand card. Rename a strand everywhere with Ctrl+R (Edit → Rename strand…); Edit → Remove unused strands… tidies up; File → Import strands… brings them in from another board

## Files

- **Open and save** [browser]: File → Open… (Ctrl+O), or drop a .json board on the page. Save (Ctrl+S) writes back to the file in Chrome and Edge; other browsers download a fresh copy each time. Save as… is Ctrl+Shift+S. Leaving with unsaved changes asks first
- **Open and save** [desktop]: File → Open… (Ctrl+O), Open recent, or drop a .json board on the window. Save (Ctrl+S) writes back to the board's file; Save as… is Ctrl+Shift+S. Closing a window with unsaved changes asks: Save, Don't save or Cancel
- **Autosave** [browser]: File → Autosave (on by default): a minute after a change, a board with a file is saved to it (Chrome and Edge), otherwise a draft is kept in the browser. The toolbar says when it last did
- **Autosave** [desktop]: File → Autosave (on by default): a minute after a change, the board is saved to its file; an untitled board is kept as a draft. The toolbar says when it last did
- **Recover unsaved work** [browser]: A board whose tab closed without being saved is offered back the next time you open Heddle in this browser: Recover, Delete or Not now
- **Recover unsaved work** [desktop]: A board whose window closed without being saved (Heddle crashed, or the computer stopped) is offered back the next time you start Heddle: Recover, Delete or Not now
- **Open recent** [browser]: File → Open recent lists the last 10 board files (Chrome and Edge)
- **Open recent** [desktop]: File → Open recent lists the last 10 board files. The first time Heddle starts, it lists the ones the Python app had open
- **Restore an earlier version** [browser]: File → Restore from backup…: the file as it was before you saved over it (the first save each session, then at most every 5 minutes). Restoring is an undoable change; nothing is written until you save
- **Restore an earlier version** [desktop]: File → Restore from backup…: the file as it was before you saved over it (the first save each session, then at most every 5 minutes), kept in %LOCALAPPDATA%\Heddle\backups with the Python app's. Restoring is an undoable change; nothing is written until you save
- **Changed elsewhere** [browser]: If a board's file was changed outside this tab, saving asks before overwriting it (the other version is backed up first). Opening a file that's open in another tab says so
- **Changed elsewhere** [desktop]: If a board's file was changed outside this window, saving asks before overwriting it (the other version is backed up first)
- **Export text**: File → Export story as text…: the board, the selected cards or the route being read, as a document or an outline in Markdown
- **Export an image** [browser]: File → Export board as image…: PNG (1×, 2× or 3×), SVG, or PDF through the browser's Print (choose Save as PDF). Handles, toggles, the grid and the selection aren't drawn
- **Export an image** [desktop]: File → Export board as image…: PNG (1×, 2× or 3×), SVG, or PDF (one page the board's shape, sharp at any size). Handles, toggles, the grid and the selection aren't drawn

## View and settings

- **Menus**: The toolbar has File, Edit, Panels and View menus. Panels open in a sidebar on the right; ⇤ / ⇥ moves one to the other side, and the layout is remembered
- **Zoom** [browser]: Ctrl+scroll or pinch (or the plain wheel, if *Mouse wheel zooms* is on in Settings); Ctrl+0 or the % button for actual size; *Fit* shows the whole board
- **Zoom** [desktop]: Ctrl+scroll or pinch (or the plain wheel, if *Mouse wheel zooms* is on in Settings); Ctrl+0 or the % button for actual size; Ctrl+1 or *Fit* shows the whole board
- **Pan**: Scroll (Shift+scroll: sideways), middle-drag, or hold Space and drag
- **Minimap**: The overview in the bottom-right corner: click to jump, drag to pan, double-click to fit; − hides it and ▣ brings it back
- **Undo / redo**: Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z), up to 200 steps
- **Settings** [browser]: Ctrl+, (Edit → Settings…): keep what's typed in a chip box on OK, mouse wheel zooms, bars over the canvas, snap to grid. Kept by this browser, not with the board. The error log is there too
- **Settings** [desktop]: Ctrl+, (Edit → Settings…): keep what's typed in a chip box on OK, mouse wheel zooms, bars over the canvas, snap to grid. Kept on this computer, not with the board. The error log is there too
- **Theme**: View → Theme: system, light or dark
- **Something went wrong** [browser]: An unexpected error shows a message with *Copy error report*; the details are kept in this browser's error log (Settings). Nothing is sent anywhere
- **Something went wrong** [desktop]: An unexpected error shows a message with *Copy error report*; the details are also written to %LOCALAPPDATA%\Heddle\logs\error.log. Nothing is sent anywhere
- **Help**: F1, or ? in the toolbar, shows these controls

## Windows [desktop]

- **A window per board**: File → Open…, Open recent or dropping a board brings it forward if it's already open in a window; otherwise it opens in this window if it's blank, else in a new one. File → New board opens a new window. A board can't be saved over one that's open in another window
- **Close**: Closing a window with unsaved changes asks first: Save, Don't save or Cancel
- **Open from outside**: `Heddle.exe board.json`, or opening a .json board with Heddle: Heddle runs once, so the board opens as a window of the running app (or comes forward if it's open)
- **Window size**: Remembered; a new window opens just down and right of the one in front

## Keys the browser keeps [browser]

- **Different from the desktop app**: Add card is N (Ctrl+Shift+N opens a private window), Character thread is T (Ctrl+T opens a tab), and Fit is the toolbar button (Ctrl+1 switches tabs)
- **On a Mac**: Cmd works where Ctrl is written, except Cmd+H (hides the browser) and Cmd+, (the browser's settings): use Edit → Replace… and Edit → Settings… instead
- **Keys Heddle takes over**: Ctrl+P, Ctrl+H, Ctrl+E, Ctrl+L, Ctrl+R, Ctrl+D, Ctrl+Shift+A, Ctrl+Shift+B, Ctrl+Shift+K, Ctrl+Shift+L, Ctrl+Shift+O and Ctrl+Shift+R do Heddle's thing while its page has the keyboard, not the browser's (print, history, reload and so on)
