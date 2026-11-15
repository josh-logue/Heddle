"""Main application window: menus, toolbar, file handling."""
from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from pathlib import Path

import shiboken6
from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QSizePolicy,
    QToolButton, QWidget,
)

from . import settings as app_settings
from . import theme
from .filter_panel import FilterPanel
from .details_form import STATUS_PRESETS
from .model import (
    CLIPBOARD_MIME, FORMAT_VERSION, RENAMABLE_FIELDS, BoardData, load_board, save_board, strands_for_file,
    strands_from_file,
)
from .backup_dialog import BackupDialog
from .filter_banner import FilterBanner, HighlightBanner
from .board_options import BoardOptionsDialog
from .minimap import Minimap
from .routes_panel import RoutesPanel
from .card_list import CardListPanel
from .card_panel import CardPanel
from .strands_panel import StrandsPanel
from .backups import backup_dir_for, file_digest, list_backups, make_backup
from .filters import FilterCounts, describe_counts, search_cards
from .checks_panel import ChecksPanel
from .export import export_route, export_text
from .export_dialogs import SCOPE_ROUTE, SCOPE_SELECTION, ExportImageDialog, ExportTextDialog
from .export_image import ExportTooLarge, export_image
from .go_to_card import GoToCardDialog
from .help_dialog import HelpDialog
from .path_reader import PathReader
from .recovery import RecoveryFile, orphans
from .search_bar import SearchBar
from .shortcuts import KEYS
from .settings_dialog import SettingsDialog
from .values_dialog import COLORS_KEY, ValueChecklistDialog
from .scene import BoardScene
from .view import BoardView, board_files

FILE_FILTER = "WarpingWeft files (*.json);;All files (*)"
RECENT_MAX = 10
SEARCH_FLASH_MS = 700  # how long a search match's outline flashes
AUTOSAVE_MS = 60_000
AUTOSAVE_RETRY_MS = (10_000, 30_000, 60_000)  # after a failed autosave; last one repeats
AUTOSAVE_MODAL_RETRY_MS = 5_000  # a dialog was open when autosave was due: try again this soon

CASCADE = 30  # a new window opens this far down and right of the one it came from

# The controls live in controls.md (shown by the Help window, F1, and copied into the README).

# Every open board window. Opening a board that's already open brings its window to
# the front; any other board opens in a window of its own.
_windows: list[MainWindow] = []


def open_windows() -> list[MainWindow]:
    """The board windows that are open, oldest first."""
    _windows[:] = [w for w in _windows if shiboken6.isValid(w)]
    return list(_windows)


def same_file(a: Path, b: Path) -> bool:
    """Do two paths name the same file (however they're spelled)?"""
    try:
        return os.path.samefile(a, b)
    except OSError:  # one of them doesn't exist (any more)
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


NO_ARROWS_HINT_OVER = 10   # cards: a bigger board with no arrows is probably for sorting
_hinted_no_arrows: set[str] = set()  # boards given the hint this session (normalised paths)


def window_for(path: Path) -> MainWindow | None:
    """The window that has this board open, if any."""
    return next((w for w in open_windows()
                 if w.current_path is not None and same_file(w.current_path, path)), None)


class MenuPeek(QObject):
    """With the menu bar hidden, Alt still reaches the menus, as in other Windows apps:
    tapping Alt shows the menu bar until you tap it again, press Esc, click elsewhere
    or close a menu from it; Alt+letter opens that menu straight away (Alt+F: File)."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.window = window
        self._alt_alone = False   # Alt is down and no other key has been pressed with it
        self.peeking = False
        for top in window.menuBar().actions():
            if top.menu() is not None:
                top.menu().aboutToHide.connect(lambda: QTimer.singleShot(0, self._maybe_hide))
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and self.peeking:
            bar = self.window.menuBar()
            on_bar = isinstance(obj, QWidget) and (obj is bar or bar.isAncestorOf(obj))
            if not on_bar and QApplication.activePopupWidget() is None:
                self.hide()  # clicked elsewhere
            return False
        if etype not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        bar = self.window.menuBar()
        if not self.window.isActiveWindow() or (bar.isVisible() and not self.peeking):
            return False
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return False
        key = event.key()
        if etype == QEvent.Type.KeyPress:
            if key == Qt.Key.Key_Alt:
                self._alt_alone = not event.isAutoRepeat() or self._alt_alone
                return False
            self._alt_alone = False
            if key == Qt.Key.Key_Escape and self.peeking:
                self.hide()
                return True
            if event.modifiers() == Qt.KeyboardModifier.AltModifier and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                menu = self._menu_for(chr(key).lower())
                if menu is not None:
                    self.show(menu)
                    return True
            return False
        if key == Qt.Key.Key_Alt and self._alt_alone and not event.isAutoRepeat():
            self._alt_alone = False
            if self.peeking:
                self.hide()
            else:
                self.show()
            return True
        return False

    def _menu_for(self, letter: str):
        for top in self.window.menuBar().actions():
            text = top.text()
            i = text.find("&")
            if 0 <= i < len(text) - 1 and text[i + 1].lower() == letter:
                return top
        return None

    def show(self, top=None) -> None:
        """Show the menu bar for now; with `top` (Alt+letter), open that menu too."""
        bar = self.window.menuBar()
        self.peeking = True
        bar.show()
        if top is not None:
            bar.setActiveAction(top)

    def hide(self) -> None:
        self.peeking = False
        if not app_settings.get("show_menu_bar"):
            self.window.menuBar().hide()

    def _maybe_hide(self) -> None:
        """A menu closed: hide the bar again unless another of its menus is open."""
        bar = self.window.menuBar()
        if self.peeking and bar.activeAction() is None:
            self.hide()


class MainWindow(QMainWindow):
    def __init__(self, path: Path | None = None, offer_recovery: bool = True):
        """`offer_recovery`: whether to offer unsaved boards left from last time (the
        first window does; windows opened later for another board don't)."""
        super().__init__()
        _windows.append(self)
        self.settings = app_settings.store()
        if self.settings.contains("dark_mode"):
            dark = self.settings.value("dark_mode", False, type=bool)
        else:
            dark = theme.system_prefers_dark()
        theme.apply(dark)

        self.scene = BoardScene(self)
        self.view = BoardView(self.scene, self)
        self.setCentralWidget(self.view)
        self.setAcceptDrops(True)  # a board .json dropped anywhere on the window opens it
        self.view.files_dropped.connect(self.open_dropped)
        self.scene.copy_requested.connect(self.copy)
        self.scene.paste_requested.connect(self.paste)
        self.scene.can_paste = self.can_paste
        self._apply_settings()
        self.current_path: Path | None = None

        self.scene.modified.connect(lambda: self.setWindowModified(True))

        # Path reader: walks one route through the story (opened from a card).
        self.path_reader = PathReader(self.scene)
        self.reader_dock = self._side_dock("Path Reader", "PathReaderDock", self.path_reader, 260)
        self.reader_dock.visibilityChanged.connect(self._on_reader_visibility)
        self.path_reader.show_card.connect(self._show_card)
        self.scene.modified.connect(self.path_reader.refresh)
        self.scene.read_requested.connect(lambda item: self.read_from(item))
        self.scene.selectionChanged.connect(self._follow_selection_paths)

        # Story checks: dead ends, extra starts, loops, loose cards, routes.
        self.checks_panel = ChecksPanel(self.scene)
        self.checks_dock = self._side_dock("Story Checks", "StoryChecksDock", self.checks_panel, 260)
        self.checks_panel.show_cards.connect(self._show_cards)

        # Routes: every way from a start to an end, each with its own fields.
        self.routes_panel = RoutesPanel(self.scene)
        self.routes_dock = self._side_dock("Routes", "RoutesDock", self.routes_panel, 280)

        # Strands: every strand, where it's used, and its description and picture.
        self.strands_panel = StrandsPanel(self.scene)
        self.strands_dock = self._side_dock("Strands", "StrandsDock", self.strands_panel, 300)
        self.strands_panel.show_cards.connect(self._show_cards)
        self.strands_panel.remove_unused_requested.connect(self.remove_unused_values)
        self.scene.strand_card_opened.connect(self.show_strand)
        self.scene.notice.connect(lambda text: self.statusBar().showMessage(text, 5000))
        self.routes_panel.show_cards.connect(self._show_cards)

        # Card: edit the selected card in place, beside the board.
        self.card_panel = CardPanel(self.scene)
        self.card_dock = self._side_dock("Card", "CardDock", self.card_panel, 260)
        self.scene.dialog_opening.connect(self.card_panel.commit)

        # Card List: every card on the board, as a tree of its groups. It sits above
        # the Card panel, so picking a card there opens it for editing below.
        self.card_list = CardListPanel(self.scene)
        self.card_list_dock = self._side_dock("Card List", "CardListDock", self.card_list, 220)
        self.splitDockWidget(self.card_list_dock, self.card_dock, Qt.Orientation.Vertical)
        self.card_list.show_ids.connect(self._show_listed)
        self.go_to_dialog: GoToCardDialog | None = None

        self.filter_panel = FilterPanel(self.scene)
        self.filter_dock = self._side_dock("Filter", "FilterDock", self.filter_panel, 240)
        self.scene.modified.connect(self.filter_panel.refresh)
        self.filter_panel.filter_changed.connect(lambda _counts, on: self.card_list.set_filter_on(on))

        # Autosave: the first unsaved change starts a one-shot countdown; later
        # changes don't restart it, so at most ~60 s of work is ever unsaved.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_failures = 0  # consecutive failed autosaves (sets the retry delay)
        self._last_save_error = ""
        # Fingerprint of current_path as this window last loaded/saved it, to notice
        # changes made elsewhere (another computer via OneDrive, another window).
        self._disk_digest: str | None = None
        self._conflict_pending = False   # autosave found such a change; prompt queued
        self._autosave_blocked = False   # user chose not to overwrite; paused until saved
        self._backed_up: set[str] = set()  # board files already backed up this session
        # Untitled boards autosave to a recovery copy (not Documents); see recovery.py.
        self._recovery: RecoveryFile | None = None

        self._build_actions()
        self._build_menus_and_toolbar()
        self.menu_peek = MenuPeek(self)  # Alt shows the hidden menu bar
        self._canvas_only_shortcuts(
            self.act_delete, self.act_select_all, self.act_cut, self.act_copy, self.act_paste,
            self.act_duplicate, self.act_edit_selected, self.act_paths, *self.card_actions)
        self.act_snap.setChecked(self.scene.snap_to_grid)  # settings were applied before the menus existed
        self.scene.modified.connect(self._schedule_autosave)
        self._search_current: str | None = None  # id of the search match last jumped to
        self.scene.modified.connect(self._refresh_search_count)
        self.scene.history_changed.connect(self._on_history_changed)
        # The Card Face checkmarks follow the open board (and undo/redo).
        self.scene.modified.connect(self._sync_display_actions)
        self.scene.history_changed.connect(self._sync_display_actions)
        self._sync_display_actions()
        self.scene.connect_mode_changed.connect(
            lambda on: self.statusBar().showMessage(
                "Click the card or group to connect to · Esc or right-click to cancel") if on
            else self.statusBar().clearMessage())
        self._on_history_changed()

        self.filter_label = QLabel()
        self.statusBar().addPermanentWidget(self.filter_label)
        # Floating "Filter on" bar over the canvas (visible even with the panel hidden).
        self.filter_banner = FilterBanner(self.view)
        self.filter_banner.show_panel_requested.connect(self._show_filter_panel)
        self.filter_banner.clear_requested.connect(self.filter_panel.clear_selection)
        # And one for path/thread highlights, just below it.
        self.highlight_banner = HighlightBanner(self.view, above=self.filter_banner)
        self.highlight_banner.clear_requested.connect(self.scene.clear_highlight)
        self.scene.highlight_changed.connect(self.highlight_banner.update_state)
        # Overview of the whole board in the canvas's corner; minimises, never closes.
        self.minimap = Minimap(self.view, expanded=self.settings.value("minimap/expanded", True, type=bool))
        self.minimap.expanded_changed.connect(self._on_minimap_expanded)
        self.act_minimap.setChecked(self.minimap.is_expanded())
        self._filter_state = (FilterCounts(0, 0), False)
        self.filter_dock.visibilityChanged.connect(self._update_filter_indicators)
        self.filter_panel.filter_changed.connect(self._on_filter_changed)
        self.filter_panel.apply()  # pick up the initial state
        self._apply_settings()  # e.g. whether the bars over the canvas show
        self.zoom_label = QLabel("100%")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().showMessage(
            "Double-click the canvas to add a card · drag a card's ● handle to connect · F1 for controls")
        self.view.zoom_changed.connect(lambda s: self.zoom_label.setText(f"{round(s * 100)}%"))

        self.resize(1280, 820)
        self._restore_window_state()
        self.view.centerOn(0, 0)
        self._update_title()
        self.focus_canvas()
        if path is not None:
            self.open_path(path)
        elif offer_recovery:  # a board left unsaved when the app last closed? (asked once the window is up)
            QTimer.singleShot(0, self.offer_recovery)

    # ----- setup ------------------------------------------------------------
    def show_strand(self, kind: str, name: str) -> None:
        """Open Strands at a strand (a strand card was double-clicked)."""
        self.strands_dock.show()
        self.strands_dock.raise_()
        self.strands_panel.refresh()
        self.strands_panel.select(kind, name)

    def _menu_button(self, text: str, menu: QMenu, tip: str) -> QToolButton:
        """A toolbar button that opens a menu."""
        button = QToolButton()
        button.setText(text)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        return button

    def createPopupMenu(self):
        """No right-click menu over the toolbar or panels' title bars: it would offer to
        hide the toolbar, which (with the menu bar hidden) is the way to everything."""
        return None

    def _side_dock(self, title: str, object_name: str, widget: QWidget, min_width: int) -> QDockWidget:
        """A closable side panel, docked on the right (or the left), hidden at first.
        The object name lets saveState()/restoreState() remember where it was."""
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setMinimumWidth(min_width)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.hide()
        return dock

    def _dock_action(self, dock: QDockWidget, text: str, shortcut: str | None = None,
                     tip: str = "") -> QAction:
        """The dock's show/hide action, with a menu label, shortcut and status tip."""
        act = dock.toggleViewAction()
        act.setText(text)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        self.addAction(act)  # keeps the shortcut live even while the menu is closed
        return act

    def _action(self, text: str, slot, shortcut=None, tip: str = "") -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        self.addAction(act)  # keeps shortcuts live even if hidden from toolbar
        return act

    def _canvas_only_shortcuts(self, *actions: QAction) -> None:
        """Make these actions' keyboard shortcuts work only while the canvas has
        keyboard focus, so pressing Del (or Ctrl+X, H, …) while a side panel's list
        has focus doesn't act on the selected cards. Their menu and toolbar entries
        still work from anywhere: a click isn't a shortcut."""
        for act in actions:
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            # The context is judged against the widgets an action belongs to: it must
            # belong to the canvas, not the whole window (which holds the side panels).
            self.removeAction(act)
            self.view.addAction(act)

    def focus_canvas(self) -> None:
        """Give the canvas keyboard focus, so its shortcuts (Del, Ctrl+C, …) work."""
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_actions(self) -> None:
        K = QKeySequence.StandardKey
        self.act_new = self._action("&New", self.new_window, K.New, "Start a new board in a new window")
        self.act_open = self._action("&Open…", self.open_board, K.Open)
        self.act_save = self._action("&Save", self.save_board, K.Save)
        self.act_save_as = self._action("Save &As…", self.save_board_as, K.SaveAs)
        self.act_restore = self._action("&Restore from Backup…", self.restore_backup, None,
                                        "Bring back an earlier version of this board")
        self.act_export_text = self._action(
            "Story as &Text (Markdown)…", self.export_story, None,
            "Write the cards out in story order, as a document or an outline")
        self.act_export_image = self._action(
            "Board as &Image or PDF…", self.export_picture, None,
            "Save the board (or the selected cards) as a PNG, SVG or PDF")
        self.act_import_values = self._action(
            "&Import Strands…", self.import_values, None,
            "Copy tags, characters, locations, custom statuses and custom colors from another board "
            "(no cards)")
        self.act_autosave = self._action("Auto&save", self._set_autosave, None,
                                         "Save automatically 60 seconds after a change")
        self.act_autosave.setCheckable(True)
        self.act_autosave.setChecked(self.settings.value("autosave", True, type=bool))
        self.act_exit = self._action("E&xit", close_all_windows, None, "Close every window and quit")

        self.act_undo = self._action("&Undo", self.scene.undo, K.Undo, "Undo the last change")
        self.act_redo = self._action("&Redo", self.scene.redo, K.Redo, "Redo the last undone change")
        if QKeySequence(K.Redo) != QKeySequence("Ctrl+Shift+Z"):
            # Windows' standard Redo is Ctrl+Y; accept Ctrl+Shift+Z too.
            self.act_redo.setShortcuts([QKeySequence(K.Redo), QKeySequence("Ctrl+Shift+Z")])
        self.act_cut = self._action("Cu&t", self.cut, K.Cut, "Remove the selected cards and copy them")
        self.act_copy = self._action("&Copy", self.copy, K.Copy, "Copy the selected cards (groups include their cards)")
        # (A lambda: the action's "checked" flag mustn't reach paste() as a position.)
        self.act_paste = self._action("&Paste", lambda: self.paste(), K.Paste,
                                      "Paste copied cards at the mouse pointer")
        self.act_duplicate = self._action("D&uplicate", self.scene.duplicate_selected, KEYS["duplicate"],
                                          "Copy the selected cards right next to them")
        self.act_find = self._action("&Find…", lambda: self.search_bar.focus(), K.Find,
                                     "Search card titles, descriptions and notes")
        self.act_find_next = self._action("Find &Next", lambda: self._search_step(1), K.FindNext)
        self.act_find_prev = self._action("Find Pre&vious", lambda: self._search_step(-1), K.FindPrevious)
        self.act_replace = self._action("&Replace…", lambda: self.scene.open_replace_dialog(), "Ctrl+H",
                                        "Find and replace text in card titles, descriptions and notes")
        self.act_go_to = self._action("&Go to Card…", lambda: self.go_to_card(), "Ctrl+P",
                                      "Type part of a card's title and jump to it")
        self.act_edit_selected = self._action(
            "&Edit Selected Cards…", self.scene.edit_selection, KEYS["edit_selected"],
            "Edit the selected card, or the color, tags and status of several at once")
        self.act_add = self._action("&Add Card", self.add_card_at_center, "Ctrl+Shift+N",
                                    "Add a new card in the middle of the view")
        self.act_delete = self._action("&Delete Selected", self.scene.delete_selected, K.Delete)
        self.act_select_all = self._action("Select &All", self._select_all, K.SelectAll)
        self.act_rename = self._action("&Rename Strand…", lambda: self.scene.open_rename_dialog(),
                                       "Ctrl+R", "Rename a tag, character, location or status "
                                       "on every card")
        self.act_settings = self._action("Se&ttings…", self.show_settings, "Ctrl+,",
                                         "Change WarpingWeft preferences")
        self.act_remove_unused = self._action(
            "Remove &Unused Strands…", self.remove_unused_values, None,
            "Remove strands that no card or route uses (and unused custom colors)")

        self.act_zoom_in = self._action("Zoom &In", lambda: self.view.zoom_by(1.25), K.ZoomIn)
        self.act_zoom_out = self._action("Zoom &Out", lambda: self.view.zoom_by(1 / 1.25), K.ZoomOut)
        self.act_zoom_reset = self._action("&Actual Size", self.view.reset_zoom, "Ctrl+0")
        self.act_fit = self._action("&Fit All", self.view.fit_all, "Ctrl+1")
        self.act_show_details = self._action("&Show All Details",
                                             lambda: self.scene.set_all_details(True))
        self.act_hide_details = self._action("&Hide All Details",
                                             lambda: self.scene.set_all_details(False))
        self.act_collapse_all = self._action(
            "&Collapse All Groups", lambda: self.scene.set_collapsed(
                [i for i in self.scene.cards.values() if i.is_group], True),
            tip="Fold every group to its title bar (one undo step)")
        self.act_expand_all = self._action(
            "E&xpand All Groups", lambda: self.scene.set_collapsed(
                [i for i in self.scene.cards.values() if i.is_group], False),
            tip="Unfold every collapsed group (one undo step)")
        # Board display options (saved with the board, undoable): View → Card Face,
        # Arrows and Canvas, and all of them in View → Board Options….
        self.board_toggles: dict[str, QAction] = {}
        self.act_show_tags = self._board_toggle("show_tags", "Show &Tags", "Show tag pills on each card")
        self.act_show_pov = self._board_toggle(
            "show_pov", "Show &POV", "Show each card's point-of-view character on its face")
        self.act_show_characters = self._board_toggle(
            "show_characters", "Show &Characters", "Show each card's characters on its face")
        self.act_show_introductions = self._board_toggle(
            "show_introductions", "Show ★ &Introductions", "Mark cards that introduce a character with ★")
        self.act_show_group_count = self._board_toggle(
            "show_group_count", "Show &Group Card Count", "Show \"N cards\" in each group's title bar")
        self.act_show_shadows = self._board_toggle("show_shadows", "Card &Shadows", "Draw a shadow under each card")
        self.act_show_description = self._board_toggle(
            "show_description", "Show &Descriptions",
            "Show each card's description on its face (hidden: point at a card to read it)")
        self.act_show_no_description = self._board_toggle(
            "show_no_description", "Show “&No description”",
            "Write “No description” on cards without one (hidden: an otherwise empty card keeps the "
            "space; one with tags, POV or characters closes it up)")
        self.act_compact_cards = self._board_toggle(
            "compact_cards", "Co&mpact Cards",
            "While descriptions are hidden, a card with nothing else on its face is just its title bar")
        self.act_show_handles = self._board_toggle(
            "show_handles", "Connection &Handles",
            "Show the ● handle for dragging out arrows (hidden: use right-click → Connect to…)")
        self.act_show_arrow_labels = self._board_toggle(
            "show_arrow_labels", "Show Arrow &Labels", "Draw arrow labels (hidden: shown when you point at an arrow)")
        self.act_show_grid = self._board_toggle("show_grid", "Show &Grid", "Draw the background grid")
        self.act_story_tools = self._board_toggle(
            "story_tools", "Story &Tools",
            "★ introductions, Story Checks, Routes, the Path Reader and character threads "
            "(turn off for a board that just sorts things into groups)")
        self.act_board_options = self._action(
            "Board &Options…", self.edit_board_options, None, "Every display option of this board in one place")
        # How arrows are drawn: also a board option.
        self.routing_group = QActionGroup(self)
        self.routing_actions: dict[str, QAction] = {}
        for key, text, tip in (
                ("straight", "&Straight", "Arrows run straight from card to card"),
                ("curved", "&Curved", "Arrows curve between the facing sides of the two cards"),
                ("avoid", "Curved, &Avoiding Cards",
                 "Curved arrows that bend around cards in their way")):
            act = self._action(text, lambda _=False, k=key: self.scene.set_display_option("arrow_routing", k),
                               None, tip + " (saved with this board)")
            act.setCheckable(True)
            self.routing_group.addAction(act)
            self.routing_actions[key] = act
        self.act_snap = self._action(
            "S&nap to Grid", self._set_snap, None,
            "Cards land on the grid when dropped, nudged or created (also in Settings)")
        self.act_snap.setCheckable(True)
        self.act_dark = self._action("&Dark Mode", self.set_dark_mode, "Ctrl+Shift+D",
                                     "Switch between light and dark themes")
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(theme.current().dark)
        self.act_filter = self._dock_action(self.filter_dock, "&Filter", "Ctrl+L",  # Ctrl+F is search
                                            "Show or hide the filter panel")
        self.act_minimap = self._action(
            "&Minimap", lambda on: self.minimap.set_expanded(on), "Ctrl+Shift+M",
            "Expand or minimise the board overview in the canvas's corner")
        self.act_minimap.setCheckable(True)
        self.act_help = self._action("&Controls", self.show_help, "F1")
        # Paths: highlight what comes before / after a card, or read one route.
        self.act_paths = self._action(
            "Highlight &Paths", self.toggle_paths, KEYS["paths"],
            "Light up everything that can come before and after the selected card (H again clears)")
        self.act_follow_paths = self._board_toggle(
            "follow_paths", "Highlight Paths of Selection", "While on, selecting a card lights up its paths")
        self.act_follow_paths.toggled.connect(lambda on: self._follow_selection_paths())
        self.act_read = self._action(
            "&Read from Selected Card", lambda: self.read_from(), KEYS["read"],
            "Walk through the story from the selected card in the Path Reader")
        self.act_thread = self._action(
            "Character &Thread…", self.choose_thread, "Ctrl+T",
            "Light up every card featuring a character, numbered in story order")
        self.act_checks = self._dock_action(
            self.checks_dock, "Story &Checks", "Ctrl+Shift+K",
            "Show dead ends, extra starts, loops, loose cards and routes")
        self.act_routes = self._dock_action(
            self.routes_dock, "R&outes", "Ctrl+Shift+O",
            "List every route from a start to an end, each with its own fields")
        self.act_reader = self._dock_action(self.reader_dock, "Path &Reader")
        self.act_strands = self._dock_action(
            self.strands_dock, "&Strands", "Ctrl+Shift+B",
            "Every strand on the board, where it's used, and its description and picture")
        self.act_card_panel = self._dock_action(
            self.card_dock, "Card &Panel", "Ctrl+Shift+E",
            "Edit the selected card's title, description and details beside the board")
        self.act_card_list = self._dock_action(
            self.card_list_dock, "Card &List", "Ctrl+Shift+L",
            "Every card on the board, group by group in story order: click one to find it")
        self._build_card_actions()

    def _build_card_actions(self) -> None:
        """The Card menu: commands for the selected cards, groups and arrows, each with a
        key from shortcuts.KEYS. They're canvas-only (see _canvas_only_shortcuts), which is
        what makes plain letters safe. (Lambdas: `triggered` passes a checked flag.)"""
        sc = self.scene
        self.act_connect = self._action(
            "&Connect To…", lambda: sc.connect_from_selected(), KEYS["connect"],
            "Draw an arrow from the selected card or group: click the card to connect to")
        self.act_details = self._action(
            "Show or Hide &Details", lambda: sc.toggle_details_selected(), KEYS["details"],
            "Open the selected cards' details, or close them if they're all open")
        self.act_collapse = self._action(
            "C&ollapse or Expand Group", lambda: sc.toggle_collapse_selected(), KEYS["collapse"],
            "Fold the selected groups (or the groups of the selected cards), or unfold them")
        self.act_arrange = self._action(
            "&Auto-arrange Group", lambda: sc.arrange_selected_groups(), KEYS["arrange"],
            "Lay out the cards of the selected groups (or the groups of the selected cards)")
        self.act_outside = self._action(
            "&Not Part of the Story", lambda: sc.toggle_outside_selected(), KEYS["outside_story"],
            "Leave the selected cards out of the story tools, or put them back")
        self.act_reverse = self._action(
            "&Reverse Arrows", lambda: sc.reverse_selected_arrows(), KEYS["reverse"],
            "Turn the selected arrows round")
        self.act_collapse_toggle_all = self._action(
            "Collapse or Expand A&ll Groups", lambda: sc.toggle_collapse_all(), KEYS["collapse_all"],
            "Fold every group, or unfold them all if every group is folded")
        self.act_details_toggle_all = self._action(
            "Show or Hide All D&etails", lambda: sc.toggle_all_details(), KEYS["details_all"],
            "Show every card's details, or hide them all if they're all showing")
        self.act_paths_cycle = self._action(
            "Highlight Before / &After", lambda: sc.cycle_paths_mode(), KEYS["paths_cycle"],
            "Switch the path highlight between before and after, only what leads here and "
            "only what follows")
        self.card_actions = [self.act_connect, self.act_details, self.act_collapse, self.act_arrange,
                             self.act_outside, self.act_reverse, self.act_collapse_toggle_all,
                             self.act_details_toggle_all, self.act_paths_cycle]

    def _build_menus_and_toolbar(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addActions([self.act_new, self.act_open])
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        m.addActions([self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_restore, self.act_import_values])
        export = m.addMenu("&Export")
        export.addActions([self.act_export_text, self.act_export_image])
        m.addSeparator()
        m.addAction(self.act_autosave)
        m.addSeparator()
        m.addAction(self.act_exit)
        m = mb.addMenu("&Edit")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_cut, self.act_copy, self.act_paste, self.act_duplicate])
        m.addSeparator()
        m.addActions([self.act_add, self.act_edit_selected, self.act_delete, self.act_select_all])
        m.addSeparator()
        m.addActions([self.act_find, self.act_find_next, self.act_find_prev, self.act_replace,
                      self.act_go_to])
        m.addSeparator()
        m.addActions([self.act_rename, self.act_remove_unused])
        m.addSeparator()
        m.addAction(self.act_settings)
        m = mb.addMenu("&Card")
        m.addActions([self.act_connect, self.act_details, self.act_collapse, self.act_arrange])
        m.addSeparator()
        m.addActions([self.act_outside, self.act_reverse])
        m.addSeparator()
        m.addActions([self.act_collapse_toggle_all, self.act_details_toggle_all])
        m = mb.addMenu("&View")
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset, self.act_fit])
        m.addSeparator()
        m.addActions([self.act_show_details, self.act_hide_details, self.act_collapse_all,
                      self.act_expand_all])
        face = m.addMenu("Card &Face")
        face.addActions([self.act_show_tags, self.act_show_pov, self.act_show_characters,
                         self.act_show_introductions, self.act_show_group_count, self.act_show_shadows,
                         self.act_show_description, self.act_show_no_description, self.act_compact_cards])
        arrows = m.addMenu("&Arrows")
        arrows.addActions(list(self.routing_actions.values()))
        arrows.addSeparator()
        arrows.addAction(self.act_show_arrow_labels)
        canvas = m.addMenu("Ca&nvas")
        canvas.addActions([self.act_show_handles, self.act_show_grid])
        self._board_menus = [face, arrows, canvas]   # also the toolbar's Board button
        m.addAction(self.act_board_options)
        # Snapping is a setting of this computer, not of the board: kept out of the
        # board's menus (and so out of the Board button).
        m.addAction(self.act_snap)
        m.addSeparator()
        m.addActions([self.act_story_tools, self.act_paths, self.act_paths_cycle, self.act_follow_paths,
                      self.act_read,
                      self.act_thread])
        m.addSeparator()
        m.addActions([self.act_card_list, self.act_card_panel, self.act_filter, self.act_strands, self.act_reader,
                      self.act_checks, self.act_routes, self.act_minimap, self.act_dark])
        m = mb.addMenu("&Help")
        m.addAction(self.act_help)

        # The menu bar is hidden unless Settings asks for it (or Alt is pressed): every
        # menu is also in the toolbar's ☰ button, and the most used ones have buttons
        # of their own (Panels, Board).
        self.main_menu = QMenu("Menu", self)
        for top in mb.actions():
            self.main_menu.addAction(top)          # the same File / Edit / View / Help menus
        self.panels_menu = QMenu("Panels", self)
        self.panels_menu.addActions([self.act_card_list, self.act_card_panel, self.act_filter, self.act_strands,
                                     self.act_routes, self.act_checks, self.act_reader, self.act_minimap])
        self.board_menu = QMenu("Board", self)
        for sub in self._board_menus:
            self.board_menu.addMenu(sub)
        self.board_menu.addAction(self.act_board_options)
        self.board_menu.addSeparator()
        self.board_menu.addAction(self.act_story_tools)

        tb = self._toolbar = self.addToolBar("Main")
        tb.setObjectName("MainToolbar")  # needed for saveState()/restoreState()
        tb.setMovable(False)
        # Never hidden: with the menu bar gone, it's the way to everything.
        tb.toggleViewAction().setVisible(False)
        self.menu_button = self._menu_button("☰", self.main_menu,
                                             "Menu: File, Edit, View and Help (or press Alt)")
        tb.addWidget(self.menu_button)
        tb.addSeparator()
        tb.addActions([self.act_new, self.act_open, self.act_save])
        tb.addSeparator()
        tb.addActions([self.act_undo, self.act_redo])
        tb.addSeparator()
        tb.addActions([self.act_add, self.act_delete])
        tb.addSeparator()
        tb.addActions([self.act_fit, self.act_show_details, self.act_hide_details])
        tb.addSeparator()
        self.panels_button = self._menu_button("Panels", self.panels_menu,
                                               "Show or hide the side panels and the minimap")
        self.board_button = self._menu_button("Board", self.board_menu,
                                              "This board's display options (saved with it)")
        tb.addWidget(self.panels_button)
        tb.addWidget(self.board_button)
        tb.addSeparator()
        tb.addActions([self.act_filter, self.act_dark])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.search_bar = SearchBar()
        self.search_bar.query_changed.connect(self._search_changed)
        self.search_bar.step.connect(self._search_step)
        self.search_bar.cleared.connect(self.view.setFocus)
        tb.addWidget(self.search_bar)

    # ----- search -----------------------------------------------------------
    def _search_matches(self) -> list[tuple]:
        """(card item, field, snippet) for every match, in reading order."""
        items = sorted(self.scene.cards.values(),
                       key=lambda i: (round(i.card_scene_rect().top()), i.card_scene_rect().left()))
        by_id = {i.card.id: i for i in items}
        return [(by_id[cid], label, snippet)
                for cid, label, snippet in search_cards([i.card for i in items], self.search_bar.text(),
                                                        self.scene.strand_info)]

    def _search_changed(self, _text: str = "") -> None:
        matches = self._search_matches()
        self._search_current = None
        # Collapsed groups say how many matches are folded away inside them.
        self.scene.set_search_hits({m[0].card.id for m in matches})
        if matches:
            self._jump_to_match(matches, 0)
        else:
            self.search_bar.show_count(0, 0)

    def _search_step(self, direction: int) -> None:
        matches = self._search_matches()
        if not matches:
            self.search_bar.show_count(0, 0)
            return
        ids = [m[0].card.id for m in matches]
        if self._search_current in ids:
            index = (ids.index(self._search_current) + direction) % len(ids)
        else:
            index = 0 if direction > 0 else len(ids) - 1
        self._jump_to_match(matches, index)

    def _jump_to_match(self, matches: list[tuple], index: int) -> None:
        item, label, snippet = matches[index]
        self.scene.reveal([item])  # a match folded inside a collapsed group: unfold it
        self._search_current = item.card.id
        self.search_bar.show_count(index + 1, len(matches))
        self.scene.clearSelection()
        item.setSelected(True)
        self.view.centerOn(item)
        item.set_drop_highlight(True)  # brief flash so the eye finds it
        # Look the card up again when the flash ends: by then it may be gone (deleted,
        # undone, another board opened). Tied to the window, so it's dropped with it.
        QTimer.singleShot(SEARCH_FLASH_MS, self, lambda cid=item.card.id: self._end_search_flash(cid))
        hidden = " · hidden by the filter" if item.dimmed else ""
        group = self.scene.title_context(item.card.id)
        where = f" · in “{group}”" if group else ""  # which of several same-named cards
        self.statusBar().showMessage(f"{label}: {snippet}{where}{hidden}", 6000)

    def _end_search_flash(self, card_id: str) -> None:
        item = self.scene.cards.get(card_id)
        if item is not None:
            item.set_drop_highlight(False)

    def _refresh_search_count(self) -> None:
        if not self.search_bar.text().strip():
            return
        matches = self._search_matches()
        ids = [m[0].card.id for m in matches]
        index = ids.index(self._search_current) + 1 if self._search_current in ids else 0
        self.search_bar.show_count(index, len(matches))

    # ----- actions ----------------------------------------------------------
    def _on_history_changed(self) -> None:
        h = self.scene.history
        self.act_undo.setEnabled(h.can_undo())
        self.act_redo.setEnabled(h.can_redo())
        # Undoing back to the last save (or an edit that changed nothing) is "unmodified".
        at_saved = h.at_saved()
        self.setWindowModified(not at_saved)
        if at_saved:
            self._autosave_timer.stop()

    # ----- paths & the path reader ------------------------------------------------
    def _selected_card(self):
        cards = [i for i in self.scene.selectedItems() if hasattr(i, "card")]
        return cards[0] if len(cards) == 1 else None

    def toggle_paths(self) -> None:
        """H: highlight the selected card's paths, or clear them if already shown."""
        item = self._selected_card()
        if self.scene.highlight_owner() == "paths" and (
                item is None or self.scene.highlight.focus == item.card.id):
            self.scene.clear_highlight()
            return
        if item is None:
            self.statusBar().showMessage("Select one card to highlight its paths", 4000)
            return
        self.scene.highlight_paths(item)

    def _follow_selection_paths(self) -> None:
        if not self.scene.display.get("follow_paths"):
            return
        item = self._selected_card()
        if item is not None:
            self.scene.highlight_paths(item)
        elif self.scene.highlight_owner() == "paths":
            self.scene.clear_highlight()

    def choose_thread(self) -> str:
        """Ask which character to follow (the selected card's POV or first
        character is offered first), then show their thread."""
        names = self.scene.all_values("characters")
        if not names:
            self.statusBar().showMessage("No card has any characters yet", 4000)
            return ""
        item = self._selected_card()
        preferred = (item.card.pov or (item.card.characters or [""])[0]) if item else ""
        start = next((n for n, v in enumerate(names) if v.casefold() == preferred.casefold()), 0)
        name, ok = QInputDialog.getItem(self, "Character thread", "Follow which character?",
                                        names, start, False)
        if not ok:
            return ""
        label = self.scene.show_thread(name)
        if not label:
            self.statusBar().showMessage(f"No card features {name}", 4000)
        return label

    def read_from(self, item=None) -> None:
        """Open the Path Reader at a card (default: the selected one)."""
        item = item or self._selected_card()
        if item is None:
            self.statusBar().showMessage("Select one card to read from it", 4000)
            return
        self.reader_dock.show()
        self.reader_dock.raise_()
        self.path_reader.start(item.card.id)
        self.path_reader.setFocus()

    # ----- export -------------------------------------------------------------------
    def _board_title(self) -> str:
        return self.current_path.stem if self.current_path else "Untitled"

    def _export_path(self, title: str, suffix: str, filters: str) -> Path | None:
        start = str(Path(self._start_dir()) / f"{self._board_title()}{suffix}")
        path, chosen = QFileDialog.getSaveFileName(self, title, start, filters)
        if not path:
            return None
        p = Path(path)
        if not p.suffix:  # take the extension from the chosen file type
            ext = chosen[chosen.find("*.") + 1:chosen.find(")")] if "*." in chosen else suffix
            p = p.with_name(p.name + ext)
        return p

    def export_story(self) -> Path | None:
        """File → Export → Story as Text: the board, the selection or the route being
        read, in story order, as Markdown."""
        has_selection = self._selected_cards_any()
        dialog = ExportTextDialog(has_selection, bool(self.path_reader.route), self)
        if not dialog.exec():
            return None
        path = self._export_path("Export story", ".md", "Markdown (*.md);;Plain text (*.txt)")
        if path is None:
            return None
        scope, options = dialog.scope_choice(), dialog.options()
        board = self.scene.to_board_data()
        if scope == SCOPE_ROUTE:
            text = export_route(board, self.path_reader.route, self.path_reader.via,
                                f"{self._board_title()}: a route", options)
        else:
            include = None
            if scope == SCOPE_SELECTION:
                include = {i.card.id for i in self.scene.selectedItems() if hasattr(i, "card")}
            text = export_text(board, self.scene.story_graph(), self._board_title(), options, include)
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Couldn't export", f"{path}\n\n{exc}")
            return None
        self.statusBar().showMessage(f"Exported to {path}", 6000)
        self.focus_canvas()
        return path

    def export_picture(self) -> Path | None:
        """File → Export → Board as Image or PDF."""
        dialog = ExportImageDialog(self._selected_cards_any(), self)
        if not dialog.exec():
            return None
        path = self._export_path("Export board", ".png",
                                 "PNG image (*.png);;SVG drawing (*.svg);;PDF document (*.pdf)")
        if path is None:
            return None
        try:
            export_image(self.scene, path, dialog.options())
        except ExportTooLarge as exc:
            QMessageBox.warning(self, "Image too large", str(exc))
            return None
        except ValueError as exc:
            QMessageBox.warning(self, "Couldn't export", str(exc))
            return None
        except OSError as exc:
            QMessageBox.critical(self, "Couldn't export", f"{path}\n\n{exc}")
            return None
        self.statusBar().showMessage(f"Exported to {path}", 6000)
        self.focus_canvas()
        return path

    def _selected_cards_any(self) -> bool:
        return any(hasattr(i, "card") for i in self.scene.selectedItems())

    def _show_cards(self, items) -> None:
        """Select some cards and bring them into view (story check results)."""
        if not items:
            return
        self.scene.reveal(items)  # e.g. a story check result inside a collapsed group
        self.scene.clearSelection()
        rect = items[0].card_scene_rect()
        for item in items:
            item.setSelected(True)
            rect = rect.united(item.card_scene_rect())
        self.view.centerOn(rect.center())
        self.focus_canvas()  # e.g. a Story Checks result: Del now acts on the found cards

    def go_to_card(self) -> GoToCardDialog:
        """Open the Go to Card box (Ctrl+P). It doesn't block: Enter picks a card and
        _go_to_card jumps there."""
        if self.go_to_dialog is not None:
            self.go_to_dialog.deleteLater()
        dialog = self.go_to_dialog = GoToCardDialog(self.scene, self)
        dialog.card_chosen.connect(self._go_to_card)
        dialog.open()
        return dialog

    def _go_to_card(self, card_id: str) -> None:
        item = self.scene.cards.get(card_id)
        if item is None:  # gone meanwhile
            return
        self._show_card(item)  # unfolds its groups, selects it, brings it into view
        group = self.scene.title_context(card_id)
        where = f" in “{group}”" if group else ""
        self.statusBar().showMessage(f"Went to “{item.card.title.strip() or 'Untitled'}”{where}", 5000)
        # After the box has closed and handed focus back to wherever it was.
        QTimer.singleShot(0, self, self.focus_canvas)

    def _show_listed(self, ids: list, unfold: bool) -> None:
        """Cards picked in the Card List: select them and bring them into view. A card
        folded inside a collapsed group can't be selected, so its group is, unless
        `unfold` (Enter or a double-click), which opens the group and hands the
        keyboard to the canvas."""
        items = [self.scene.cards[i] for i in ids if i in self.scene.cards]
        if not items:
            return
        if unfold:
            self.scene.reveal(items)
            targets = items
        else:
            targets = list(dict.fromkeys(self.scene.visible_end(i) for i in items))
        self.scene.clearSelection()
        rect = targets[0].card_scene_rect()
        for item in targets:
            item.setSelected(True)
            rect = rect.united(item.card_scene_rect())
        self.view.centerOn(rect.center())
        folded = [i for i in items if not unfold and self.scene.visible_end(i) is not i]
        if folded:
            group = self.scene.visible_end(folded[0])
            title = folded[0].card.title.strip() or "Untitled"
            self.statusBar().showMessage(
                f"“{title}” is inside the collapsed group “{group.card.title.strip() or 'Untitled'}”"
                " · Enter or double-click opens it", 6000)
        if unfold:
            # Del, D, C… now act on the card. After the click that asked for it, which
            # would otherwise leave the keyboard in the list.
            QTimer.singleShot(0, self, self.focus_canvas)

    def _show_card(self, item) -> None:
        """Select a card and bring it into view (the reader's steps)."""
        self.scene.reveal([item])
        self.scene.clearSelection()
        item.setSelected(True)
        self.view.centerOn(item)

    def _on_reader_visibility(self, visible: bool) -> None:
        if not visible and not self.isMinimized():
            self.path_reader.stop()  # closing the panel ends the reading and its highlight

    def _sync_display_actions(self) -> None:
        """Menus follow the open board's options (and undo/redo of them)."""
        for key, act in self.board_toggles.items():
            act.setChecked(bool(self.scene.display.get(key)))
        # "No description" only matters while descriptions show, Compact Cards only while
        # they're hidden: grey out the one that doesn't apply (it keeps its tick).
        shown = bool(self.scene.display.get("show_description", True))
        self.act_show_no_description.setEnabled(shown)
        self.act_compact_cards.setEnabled(not shown)
        routing = self.scene.display.get("arrow_routing", "straight")
        self.routing_actions.get(routing, self.routing_actions["straight"]).setChecked(True)
        self._apply_story_tools(bool(self.scene.display.get("story_tools", True)))

    def _apply_story_tools(self, on: bool) -> None:
        """Story tools off: their menu items (and shortcuts) go, and their panels close."""
        for act in (self.act_read, self.act_thread, self.act_checks, self.act_routes, self.act_reader,
                    self.act_outside):
            act.setVisible(on)
        if not on:
            for dock in (self.checks_dock, self.routes_dock, self.reader_dock):
                if dock.isVisible():
                    dock.hide()

    def _board_toggle(self, key: str, text: str, tip: str) -> QAction:
        """A checkable menu item for one of the board's on/off display options."""
        act = QAction(text, self)
        act.setStatusTip(tip + " (saved with this board)")
        act.setCheckable(True)
        # toggled, not triggered: ticking it from code acts like a click. When the menus
        # are synced to the board, the value is already the board's, so nothing changes.
        act.toggled.connect(lambda on, k=key: self.scene.set_display_option(k, on))
        self.addAction(act)
        self.board_toggles[key] = act
        return act

    def edit_board_options(self) -> bool:
        """View → Board Options…: all the board's display options; OK is one undo step."""
        dialog = BoardOptionsDialog(self.scene.display, self)
        if not dialog.exec():
            return False
        self.scene.set_display_options(dialog.values())
        return True

    def _on_filter_changed(self, counts: FilterCounts, active: bool) -> None:
        self._filter_state = (counts, active)
        self._update_filter_indicators()

    def _update_filter_indicators(self, *_args) -> None:
        """Keep every sign of an active filter in step: status bar text, the banner
        over the canvas, and the toolbar button's highlight and count."""
        counts, active = self._filter_state
        shown = describe_counts(counts)
        self.filter_label.setText(f"Filter active: {shown} shown" if active else "")
        self.filter_banner.update_state(counts, active, self.filter_dock.isVisible(),
                                        self.filter_panel.match_note() if active else "")
        n = self.filter_panel.selected_count() if active else 0
        self.act_filter.setText(f"&Filter ({n})" if n else "&Filter")
        button = self._toolbar.widgetForAction(self.act_filter)
        if button is not None:
            button.setStyleSheet(theme.filter_button_stylesheet(active))
            button.setToolTip(f"Filter is on: {shown} shown (Ctrl+L)" if active
                              else "Show or hide the filter panel (Ctrl+L)")

    def _on_minimap_expanded(self, expanded: bool) -> None:
        self.act_minimap.setChecked(expanded)
        self.settings.setValue("minimap/expanded", expanded)

    def _show_filter_panel(self) -> None:
        self.filter_dock.show()
        self.filter_dock.raise_()
    def set_dark_mode(self, dark: bool) -> None:
        """The theme is app-wide: every open window follows."""
        theme.apply(dark)
        self.settings.setValue("dark_mode", dark)
        for w in open_windows():
            w._refresh_theme()

    def _refresh_theme(self) -> None:
        self.act_dark.setChecked(theme.current().dark)
        self.filter_panel.apply_theme()
        self.filter_banner.apply_theme()
        self.highlight_banner.apply_theme()
        self.minimap.apply_theme()
        self.routes_panel.refresh()  # its muted "from cards" text follows the theme
        for item in self.scene.items():
            item.update()  # also refreshes cards' cached pixmaps, which scene.update() keeps
        self.scene.update()
        self.view.viewport().update()
    # ----- clipboard ------------------------------------------------------------
    def copy(self) -> bool:
        fragment = self.scene.selection_fragment()
        if fragment is None:
            return False
        self._put_on_clipboard(fragment)
        return True

    def cut(self) -> bool:
        fragment = self.scene.cut_selected()
        if fragment is None:
            return False
        self._put_on_clipboard(fragment)
        return True

    def _put_on_clipboard(self, fragment) -> None:
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, json.dumps(fragment.to_dict()).encode("utf-8"))
        mime.setText("\n".join(c.title for c in fragment.cards))  # readable in a text editor
        QApplication.clipboard().setMimeData(mime)
        n = len(fragment.cards)
        self.statusBar().showMessage(f"Copied {n} card{'s' if n != 1 else ''}", 3000)

    @staticmethod
    def can_paste() -> bool:
        mime = QApplication.clipboard().mimeData()
        return mime is not None and mime.hasFormat(CLIPBOARD_MIME)

    def paste(self, at: QPointF | None = None) -> int:
        """Paste copied cards: at `at`, else at the mouse if it's over the board, else
        just beside the originals. Works across windows and boards."""
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(CLIPBOARD_MIME):
            return 0
        try:
            fragment = BoardData.from_dict(json.loads(bytes(mime.data(CLIPBOARD_MIME)).decode("utf-8")))
        except (ValueError, TypeError):
            return 0
        if not isinstance(at, QPointF):  # (e.g. a stray True/False from a signal)
            at = self._mouse_on_canvas()
        return len(self.scene.paste_fragment(fragment, at))

    def _mouse_on_canvas(self) -> QPointF | None:
        vp = self.view.viewport()
        pos = vp.mapFromGlobal(QCursor.pos())
        return self.view.mapToScene(pos) if vp.rect().contains(pos) and vp.underMouse() else None

    def add_card_at_center(self) -> None:
        self.scene.create_card_at(self.view.mapToScene(self.view.viewport().rect().center()))

    def _select_all(self) -> None:
        """Every card, group and arrow on show, as one selection change (selecting them
        one by one signalled once per item, and every listener rescanned the selection)."""
        area = QPainterPath()
        area.addRect(self.scene.itemsBoundingRect().united(self.scene.sceneRect()))
        self.scene.setSelectionArea(area, Qt.ItemSelectionOperation.ReplaceSelection,
                                    Qt.ItemSelectionMode.IntersectsItemBoundingRect)

    def show_settings(self) -> None:
        SettingsDialog(self).exec()
        for w in open_windows():  # app-wide preferences: every window follows
            w._apply_settings()

    def _apply_settings(self) -> None:
        self.menuBar().setVisible(app_settings.get("show_menu_bar"))
        self.view.wheel_zooms = app_settings.get("wheel_zooms")
        snap = app_settings.get("snap_to_grid")
        self.scene.snap_to_grid = snap
        if hasattr(self, "act_snap"):
            self.act_snap.setChecked(snap)
        if hasattr(self, "filter_banner"):  # floating bars over the canvas (status bar keeps the state)
            banners = app_settings.get("show_banners")
            self.filter_banner.set_enabled(banners)
            self.highlight_banner.set_enabled(banners)
            self._update_filter_indicators()
            self.highlight_banner.update_state(self.scene.highlight_label() if self.scene.highlight else "")

    def _set_snap(self, on: bool) -> None:
        app_settings.set("snap_to_grid", on)
        self._apply_settings()

    def show_help(self) -> HelpDialog:
        """F1: the controls, in a scrollable window (one at a time; F1 again brings it forward)."""
        if getattr(self, "_help", None) is None:
            self._help = HelpDialog(self)
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()
        return self._help

    # ----- files ------------------------------------------------------------
    def _update_title(self) -> None:
        name = self.current_path.stem if self.current_path else "Untitled"
        self.setWindowTitle(f"{name}[*] — WarpingWeft")

    @staticmethod
    def _documents_dir() -> Path:
        # Resolves OneDrive-redirected Documents correctly, unlike ~/Documents.
        loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(loc) if loc else Path.home() / "Documents"

    def _start_dir(self) -> str:
        if self.current_path:
            return str(self.current_path.parent)
        return str(self._documents_dir())

    # ----- autosave ---------------------------------------------------------
    def _set_autosave(self, enabled: bool) -> None:
        self.settings.setValue("autosave", enabled)
        if not enabled:
            self._autosave_timer.stop()
            self._autosave_failures = 0
        elif self.isWindowModified():
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if (self.act_autosave.isChecked() and not self._autosave_blocked
                and not self._autosave_timer.isActive()):
            # Pass the delay explicitly: start(ms) also changes the timer's stored
            # interval, so a previous retry delay would otherwise stick.
            self._autosave_timer.start(AUTOSAVE_MS)

    def _autosave(self) -> None:
        if (not self.isWindowModified() or not self.act_autosave.isChecked()
                or self._autosave_blocked):
            return
        if QApplication.activeModalWidget() is not None:
            # A dialog is open, e.g. the editor for a card that cancelling would remove
            # again: don't save that half-made state; try again shortly.
            self._autosave_timer.start(AUTOSAVE_MODAL_RETRY_MS)
            return
        if self.current_path is None:
            self._autosave_recovery()
            return
        path = self.current_path
        if self._write(path, quiet=True):
            self.statusBar().showMessage(f"Autosaved to {path}", 5000)
        elif self._conflict_pending:
            # The file changed on disk: _resolve_autosave_conflict asks; no retry timer.
            self._autosave_timer.stop()
        else:
            # Often a brief lock (e.g. OneDrive syncing): try again on our own rather
            # than waiting for the next edit, backing off 10 s → 30 s → 60 s.
            delay = AUTOSAVE_RETRY_MS[min(self._autosave_failures, len(AUTOSAVE_RETRY_MS) - 1)]
            self._autosave_failures += 1
            self._autosave_timer.start(delay)
            self.statusBar().showMessage(
                f"Autosave failed ({self._last_save_error}); retrying in {delay // 1000} s", delay)

    # ----- recovery copies of untitled boards -------------------------------------
    def _autosave_recovery(self) -> None:
        """Untitled: keep a recovery copy in the app's data folder. The board stays
        untitled and unsaved (closing still asks), so nothing lands in Documents."""
        self.scene.flush_history()
        try:
            if self._recovery is None:
                self._recovery = RecoveryFile.create()
            self._recovery.write(self.scene.to_board_data())
        except OSError as exc:
            self._autosave_failures += 1
            delay = AUTOSAVE_RETRY_MS[min(self._autosave_failures - 1, len(AUTOSAVE_RETRY_MS) - 1)]
            self._autosave_timer.start(delay)
            self.statusBar().showMessage(
                f"Autosave failed ({exc.strerror or exc}); retrying in {delay // 1000} s", delay)
            return
        self._autosave_failures = 0
        self.statusBar().showMessage(
            "Autosaved a recovery copy · this board is untitled: Save to keep it", 5000)

    def _drop_recovery(self) -> None:
        """The untitled board was saved properly or thrown away: remove its copy."""
        if self._recovery is not None:
            try:
                self._recovery.discard()
            except OSError:
                pass  # e.g. already gone; nothing to recover either way
            self._recovery = None

    def offer_recovery(self) -> bool:
        """If an untitled board was left unsaved when the app last closed, offer to
        bring it back (into this window, while it's still empty). Returns True if it
        was recovered."""
        if self.current_path is not None or self.scene.cards or self._recovery is not None:
            return False
        found = orphans()
        if not found:
            return False
        path, lock = found[0]
        for _, other in found[1:]:
            other.unlock()  # older copies wait for a later launch
        try:
            board = load_board(path)
        except (OSError, ValueError, TypeError):
            RecoveryFile(path, lock).discard()  # unreadable: nothing to recover
            return False
        when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %Y, %H:%M")
        n = len(board.cards)
        more = f"\n\n({len(found) - 1} older unsaved board(s) will be offered next time.)" \
            if len(found) > 1 else ""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Recover unsaved board")
        box.setText("WarpingWeft closed without saving an untitled board.")
        box.setInformativeText(f"It was last autosaved {when} and has {n} card{'s' if n != 1 else ''}. "
                               f"Recover it?{more}")
        recover = box.addButton("Recover", QMessageBox.ButtonRole.AcceptRole)
        delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(recover)
        box.exec()
        if box.clickedButton() is delete:
            RecoveryFile(path, lock).discard()
            return False
        if box.clickedButton() is not recover:
            lock.unlock()
            return False
        self.scene.load_board_data(board)
        self.scene.reset_history()
        self.scene.history.saved = None  # it's never been saved: closing will ask
        self._recovery = RecoveryFile(path, lock)  # keep autosaving to the same copy
        self.filter_panel.reset()
        self._update_title()
        self._on_history_changed()
        self.setWindowModified(True)
        self.view.fit_all()
        self.statusBar().showMessage("Recovered an unsaved board · Save to keep it", 8000)
        return True

    def maybe_save(self) -> bool:
        """Return True if it's OK to discard the current board."""
        if not self.isWindowModified():
            return True
        btn = QMessageBox.question(
            self, "Unsaved changes", "Save changes to this board first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if btn == QMessageBox.StandardButton.Save:
            return self.save_board()
        return btn == QMessageBox.StandardButton.Discard

    def is_blank(self) -> bool:
        """An untitled, untouched, empty board: opening a board can use this window."""
        return self.current_path is None and not self.isWindowModified() and not self.scene.cards

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def spawn_window(self) -> MainWindow:
        """A new, empty board window, just down and right of this one."""
        win = MainWindow(offer_recovery=False)
        if self.isMaximized():
            win.showMaximized()
        else:
            win.resize(self.size())
            win.move(self.pos() + QPoint(CASCADE, CASCADE))
            win.show()
        win.bring_to_front()
        return win

    def new_window(self) -> MainWindow:
        """File → New: a new board in a new window (this one, if it's still blank)."""
        if self.is_blank():
            self.bring_to_front()
            self.focus_canvas()
            return self
        return self.spawn_window()

    def request_open(self, path: Path) -> MainWindow | None:
        """Open a board as File → Open does. Already open in a window: that window comes
        to the front. Otherwise it opens here if this window is still blank, else in a
        new window; the board shown here is never replaced. Returns the window showing
        it, or None if it couldn't be opened (the reason is shown)."""
        path = Path(path)
        existing = window_for(path)
        if existing is not None:
            existing.bring_to_front()
            return existing
        if self.is_blank():
            self.open_path(path)
            return self if self.current_path is not None else None
        try:  # check it opens before making a window for it
            load_board(path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Couldn't open file", f"{path}\n\n{exc}")
            return None
        win = self.spawn_window()
        win.open_path(path)
        if win.current_path is None:  # damaged in a way only loading it showed
            win.close()
            return None
        return win

    def new_board(self) -> None:
        """Replace this window's board with a new, empty one (asking about unsaved
        changes first). File → New opens a new window instead (new_window)."""
        if not self.maybe_save():
            return
        self._autosave_timer.stop()
        self._drop_recovery()
        self.scene.clear_board()
        self.scene.reset_history()
        self.filter_panel.reset()
        self.path_reader.stop()
        self.current_path = None
        self._disk_digest = None
        self._autosave_blocked = False
        self.setWindowModified(False)
        self._update_title()
        self.view.reset_zoom()
        self.view.centerOn(0, 0)
        self.focus_canvas()

    def open_board(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open board", self._start_dir(), FILE_FILTER)
        if path:
            self.request_open(Path(path))

    def open_path(self, path: Path) -> None:
        try:
            board = strands_from_file(load_board(path), Path(path).parent)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Couldn't open file", f"{path}\n\n{exc}")
            return
        try:
            # All-or-nothing: on failure the current board is left exactly as it was.
            self.scene.load_board_data(board)
        except Exception as exc:  # any damage the model checks didn't catch
            self.filter_panel.refresh()  # re-dim the restored cards if a filter is on
            QMessageBox.critical(self, "Couldn't open file",
                                 f"{path}\n\nThe file is damaged and couldn't be loaded "
                                 f"({type(exc).__name__}: {exc}).\nYour current board is unchanged.")
            return
        self._autosave_timer.stop()
        self._drop_recovery()  # the untitled board was saved or discarded by maybe_save
        self.scene.reset_history()
        self.filter_panel.reset()
        self.path_reader.stop()
        self.current_path = Path(path)
        self._disk_digest = file_digest(self.current_path)
        self._autosave_blocked = False
        self._add_recent(self.current_path)
        self.setWindowModified(False)
        self._update_title()
        self.view.fit_all()
        self.focus_canvas()
        self._hint_story_tools()
        if board.load_notes:
            QMessageBox.information(
                self, "Board repaired while opening",
                f"“{self.current_path.name}” had some damaged entries, so it was opened "
                "without them:\n\n• " + "\n• ".join(board.load_notes) +
                "\n\nSaving writes the repaired board.")
        if board.from_newer_version:
            QMessageBox.warning(
                self, "Board from a newer version",
                f"“{self.current_path.name}” was saved by a newer version of WarpingWeft "
                f"(file format {board.source_version}; this version understands up to "
                f"{FORMAT_VERSION}).\n\nIt has opened, but anything stored by newer features "
                "may be lost if you save it from this version.")

    def _hint_story_tools(self) -> bool:
        """A board used for sorting (many cards, no arrows) with story tools on gets a
        one-time hint, once per board per session: ★, Story Checks and threads mean
        nothing without arrows."""
        s = self.scene
        if not s.display.get("story_tools", True) or s.edges or len(s.cards) <= NO_ARROWS_HINT_OVER:
            return False
        key = os.path.normcase(os.path.realpath(self.current_path)) if self.current_path else ""
        if not key or key in _hinted_no_arrows:
            return False
        _hinted_no_arrows.add(key)
        self.statusBar().showMessage("No arrows on this board · turn off Story Tools? (Board → Story Tools)",
                                     12000)
        return True

    # ----- recent files & dropped files ---------------------------------------
    def recent_files(self) -> list[Path]:
        raw = self.settings.value("recent_files", [])
        if isinstance(raw, str):  # QSettings returns a lone string for a 1-item list
            raw = [raw]
        return [Path(p) for p in (raw or []) if isinstance(p, str) and p]

    def _set_recent_files(self, paths: list[Path]) -> None:
        self.settings.setValue("recent_files", [str(p) for p in paths[:RECENT_MAX]])

    def _add_recent(self, path: Path) -> None:
        path = Path(path).resolve()
        current = self.recent_files()
        if current and os.path.normcase(current[0]) == os.path.normcase(path):
            return  # already on top (e.g. every autosave): nothing to write
        key = os.path.normcase(path)
        self._set_recent_files([path] + [p for p in current if os.path.normcase(p) != key])

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.recent_files()
        for n, path in enumerate(files, start=1):
            label = f"&{n % 10} {path.name}" if n <= 10 else path.name
            act = self.recent_menu.addAction(label, lambda p=path: self.open_recent(p))
            act.setStatusTip(str(path))
        if files:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear List", lambda: self._set_recent_files([]))
        else:
            self.recent_menu.addAction("No recent boards").setEnabled(False)

    def open_recent(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.information(self, "Open recent",
                                    f"“{path.name}” can no longer be found, so it has been removed "
                                    f"from the list.\n\n{path}")
            self._set_recent_files([p for p in self.recent_files()
                                    if os.path.normcase(p) != os.path.normcase(path)])
            return
        self.request_open(path)

    def open_dropped(self, files: list[Path]) -> None:
        """Board files dropped on the window: each opens as File → Open would (here
        if this window is blank, else in a window of its own)."""
        for path in files:
            self.request_open(path)

    def dragEnterEvent(self, event) -> None:
        if board_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        files = board_files(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.open_dropped(files)

    # ----- strands (the entries in tags, characters, locations, status) -------
    def import_values(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import strands from board",
                                              self._start_dir(), FILE_FILTER)
        if path:
            self.import_values_from(Path(path))

    def import_values_from(self, path: Path) -> int:
        """Offer the strands (and custom colours) in another board file that this board
        doesn't have yet."""
        try:
            source = strands_from_file(load_board(path), Path(path).parent)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Couldn't read file", f"{path}\n\n{exc}")
            return 0
        new: dict[str, list[str]] = {}
        for f in RENAMABLE_FIELDS:
            have = {v.casefold() for v in self.scene.all_values(f)}
            if f == "status":  # the built-in presets are always offered; only custom ones matter
                have |= {s.casefold() for s in STATUS_PRESETS if s}
            fresh = [v for v in source.all_values(f) if v.casefold() not in have]
            if fresh:
                new[f] = fresh
        colors = [c for c in source.custom_colors if c not in self.scene.custom_colors]
        if colors:
            new[COLORS_KEY] = colors
        if not new:
            QMessageBox.information(self, "Import strands",
                                    f"“{path.stem}” has no strands or custom colors this board "
                                    "doesn't already have.")
            return 0
        dialog = ValueChecklistDialog(
            "Import strands",
            f"Strands and custom colors from <b>{escape(path.stem)}</b> that this board doesn't "
            "have yet. Checked ones are added to this board's strands; no cards are copied.",
            new, "Import", self)
        if not dialog.exec():
            return 0
        chosen = dialog.selected()
        added = self.scene.import_values({k: v for k, v in chosen.items() if k != COLORS_KEY},
                                         chosen.get(COLORS_KEY, []), source.strands)
        self.statusBar().showMessage(f"Imported {added} strand{'s' if added != 1 else ''} or "
                                     f"color{'s' if added != 1 else ''} from {path.name}", 5000)
        return added

    def remove_unused_values(self) -> int:
        unused = self.scene.unused_saved_values()
        detailed = self.scene.unused_strands()[1]
        if not unused and not detailed:
            QMessageBox.information(self, "Remove unused strands",
                                    "There are no strands or custom colors that nothing on the board uses.")
            return 0
        n = sum(len(v) for v in detailed.values())
        dialog = ValueChecklistDialog(
            "Remove unused strands",
            "Nothing on the board uses these strands or custom colors. Checked ones "
            "will be removed from this board's strands and palette.", unused, "Remove", self,
            extra=detailed,
            extra_label=f"Also list unused strands with a description, picture or fields ({n})")
        if not dialog.exec():
            return 0
        removed = self.scene.remove_saved_values(dialog.selected())
        self.statusBar().showMessage(f"Removed {removed} unused strand{'s' if removed != 1 else ''} "
                                     "or color" + ("s" if removed != 1 else ""), 5000)
        return removed

    def save_board(self) -> bool:
        if self.current_path is None:
            return self.save_board_as()
        return self._write(self.current_path)

    def save_board_as(self) -> bool:
        start = str(self.current_path) if self.current_path else str(Path(self._start_dir()) / "Untitled.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save board", start, FILE_FILTER)
        if not path:
            return False
        p = Path(path)
        if p.suffix.lower() != ".json":
            p = p.with_name(p.name + ".json")
        other = window_for(p)
        if other is not None and other is not self:
            # Two windows owning one file would overwrite each other's work.
            self._open_elsewhere(other, p)
            return False
        return self._write(p)

    def _open_elsewhere(self, other: MainWindow, path: Path) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, "Board is open in another window",
                          f"“{path.name}” is open in another window, so this board can't be "
                          "saved over it.\n\nSave under a different name, or close that "
                          "window first.", parent=self)
        show = box.addButton("Show That Window", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is show:
            other.bring_to_front()

    def _write(self, path: Path, quiet: bool = False, overwrite_changes: bool = False) -> bool:
        """Save to `path`. Refuses to silently overwrite a file that changed on disk
        since this window opened/saved it, and backs up the existing file first."""
        path = Path(path)
        self.scene.flush_history()
        changed_elsewhere = self._changed_on_disk(path)
        if changed_elsewhere and not overwrite_changes:
            if quiet:  # autosave: never overwrite; ask once the current event is done
                self._last_save_error = "the file changed on disk"
                if not self._conflict_pending:
                    self._conflict_pending = True
                    QTimer.singleShot(0, self._resolve_autosave_conflict)
                return False
            choice = self._ask_about_conflict(path)
            if choice == "save_as":
                return self.save_board_as()
            if choice != "overwrite":
                return False
        # Keep the version that's about to be replaced. Their changes are always
        # backed up when overwriting a conflict, whatever the time since the last backup.
        self._backup(path, force=changed_elsewhere)
        try:
            save_board(strands_for_file(self.scene.to_board_data(), path.parent), path)
        except OSError as exc:
            self._last_save_error = exc.strerror or str(exc)
            if not quiet:  # autosave doesn't pop a dialog mid-edit; _autosave retries
                QMessageBox.critical(self, "Couldn't save file", f"{path}\n\n{exc}")
            return False
        self._disk_digest = file_digest(path)
        self._add_recent(path)
        self._autosave_blocked = False
        self._autosave_failures = 0
        self._autosave_timer.stop()
        self.scene.history.mark_saved()
        self._on_history_changed()
        self.current_path = path
        self._drop_recovery()  # an untitled board now has a real file
        self.setWindowModified(False)
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    # ----- backups & changes on disk -----------------------------------------
    @staticmethod
    def _backup_root() -> Path:
        # Local app data (not the synced Documents folder): %LOCALAPPDATA%\WarpingWeft\backups,
        # unless WARPINGWEFT_BACKUP_DIR names another folder.
        override = os.environ.get("WARPINGWEFT_BACKUP_DIR", "").strip()
        if override:
            return Path(override)
        base = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericDataLocation))
        root = base / app_settings.APP_NAME / "backups"
        legacy = base / app_settings.LEGACY_APP_NAME / "backups"
        if not root.exists() and legacy.is_dir():
            # Backups made before the rename: move them over so Restore still finds them.
            try:
                root.parent.mkdir(parents=True, exist_ok=True)
                legacy.rename(root)
            except OSError:
                return legacy  # couldn't move (e.g. in use): keep using the old folder
        return root

    def _backup(self, path: Path, force: bool = False) -> None:
        """Copy the file about to be overwritten. Always on the first save of a board
        in this session (so the file as opened is kept), else at most every 5 minutes."""
        key = str(path.resolve()).casefold()
        try:
            make_backup(path, self._backup_root(), force=force or key not in self._backed_up)
            self._backed_up.add(key)
        except OSError as exc:  # a failed backup mustn't stop the save itself
            self.statusBar().showMessage(f"Couldn't back up {path.name}: {exc}", 8000)

    def _changed_on_disk(self, path: Path) -> bool:
        """True if `path` is the open board and its contents differ from what this
        window last loaded or saved (someone else wrote to it)."""
        if self.current_path is None or path.resolve() != self.current_path.resolve():
            return False
        if self._disk_digest is None or not path.exists():
            return False  # never read it, or it was deleted/moved: nothing to clobber
        now = file_digest(path)
        return now is not None and now != self._disk_digest

    def _ask_about_conflict(self, path: Path) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("File changed on disk")
        box.setText(f"<b>{escape(path.name)}</b> was changed outside this window since you "
                    "opened or last saved it, for example on another computer or in another "
                    "WarpingWeft window.")
        box.setInformativeText("Overwrite it with your version? The version on disk is backed "
                               "up first (File → Restore from Backup…). Or save yours as a "
                               "separate file.")
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
        save_as = box.addButton("Save As…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save_as)
        box.exec()
        clicked = box.clickedButton()
        return "overwrite" if clicked is overwrite else "save_as" if clicked is save_as else "cancel"

    def _resolve_autosave_conflict(self) -> None:
        self._conflict_pending = False
        if self.current_path is None or not self._changed_on_disk(self.current_path):
            self._schedule_autosave()  # resolved itself meanwhile
            return
        self._autosave_timer.stop()
        choice = self._ask_about_conflict(self.current_path)
        if choice == "overwrite":
            self._write(self.current_path, overwrite_changes=True)
        elif choice == "save_as":
            self.save_board_as()
        else:
            self._autosave_blocked = True
            self.statusBar().showMessage(
                "Autosave paused: the file changed on disk. Save (Ctrl+S) to choose what to do.")

    def restore_backup(self) -> None:
        if self.current_path is None:
            QMessageBox.information(self, "Restore from backup",
                                    "This board hasn't been saved yet, so it has no backups.")
            return
        backups = list_backups(self.current_path, self._backup_root())
        if not backups:
            QMessageBox.information(
                self, "Restore from backup",
                f"There are no backups of “{self.current_path.name}” yet. One is made the first "
                "time you save over it each session, then at most every 5 minutes.")
            return
        dialog = BackupDialog(self.current_path.name, backups,
                              backup_dir_for(self.current_path, self._backup_root()), self)
        if not dialog.exec() or dialog.selected_path() is None:
            return
        chosen = dialog.selected_path()
        try:
            # A backup lives elsewhere: its pictures are relative to this board's folder.
            board = strands_from_file(load_board(chosen),
                                      self.current_path.parent if self.current_path else None)
            self.scene.load_board_data(board)
        except Exception as exc:  # unreadable backup: current board is left as it was
            self.filter_panel.refresh()
            QMessageBox.critical(self, "Couldn't restore backup", f"{chosen}\n\n{exc}")
            return
        self.scene.mark_modified()  # an ordinary, undoable change to this board
        self.statusBar().showMessage(
            f"Restored the backup from {dialog.selected_label()}. Undo (Ctrl+Z) to go back; "
            "save to keep it.", 10000)

    # ----- window layout ------------------------------------------------------
    # Window size/position and the filter panel's visibility, side and width are
    # remembered between sessions. Filter *selections* are not: they belong to a
    # particular board and would silently dim cards on the next one.
    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        self._toolbar.show()  # even if a saved layout had it hidden: it's the way to everything

    def _save_window_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())

    def closeEvent(self, event) -> None:
        if self.maybe_save():
            self._drop_recovery()  # saved, or deliberately discarded
            self._save_window_state()
            event.accept()
            if self in _windows:
                _windows.remove(self)
            self.deleteLater()  # free it (and its timers) once the event loop gets to it
        else:
            event.ignore()


def close_all_windows() -> bool:
    """File → Exit: close every window, each asking about unsaved changes; stops (and
    returns False) if one is cancelled."""
    for w in reversed(open_windows()):
        if not w.close():
            w.bring_to_front()
            return False
    return True
