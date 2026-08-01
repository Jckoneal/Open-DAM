"""Search/command palette — a live-filtering, keyboard-driven window
implementing wireframe option 1c ("search-first · keyboard command
palette") from the Curate Menubar Wireframes design: type to filter project
actions, arrow keys to move the selection, Enter to run the selected one,
Escape to dismiss.

This needs real custom AppKit UI — rumps.Window is a blocking modal with no
live-filter-as-you-type capability, so there's no way to build this on top
of rumps' own primitives. Keyboard navigation uses the standard Cocoa
"text field with a suggestions list" pattern
(NSTextField delegate's control:textView:doCommandBySelector:) — the same
mechanism countless real Mac apps use for exactly this, not a from-scratch
keyDown_ reimplementation.
"""

from __future__ import annotations

from typing import Callable, List

import objc
from AppKit import (
    NSBackgroundColorAttributeName,
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSScreen,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskTitled,
    NSWindowTitleHidden,
)
from Foundation import NSMutableAttributedString, NSObject

from collaborate.menubar_model import PaletteAction, filter_actions

WIDTH = 480
HEIGHT = 300
VISIBLE_ROWS = 8


class _Delegate(NSObject):
    """The thinnest possible NSObject shim: Cocoa requires a real
    Objective-C object as an NSTextField's delegate, but all actual state
    and logic live on the plain-Python SearchPalette this just forwards to
    — keeping the custom-AppKit surface area (and its risk) as small as
    possible."""

    def initWithPalette_(self, palette):
        self = objc.super(_Delegate, self).init()
        if self is None:
            return None
        self._palette = palette
        return self

    def controlTextDidChange_(self, notification):
        self._palette._on_query_changed()

    def control_textView_doCommandBySelector_(self, control, text_view, selector):
        if selector == "moveDown:":
            self._palette._move_selection(1)
            return True
        if selector == "moveUp:":
            self._palette._move_selection(-1)
            return True
        if selector == "insertNewline:":
            self._palette._run_selected()
            return True
        if selector == "cancelOperation:":
            self._palette._dismiss()
            return True
        return False


class SearchPalette:
    """Owns the window/fields; all state (query, selection, the current
    action list) lives here as plain Python attributes, not spread across
    ObjC objects, so it stays easy to reason about and to drive
    programmatically from a test without a live event loop."""

    def __init__(self, on_run: Callable[[PaletteAction], None]):
        self._on_run = on_run
        self._all_actions: List[PaletteAction] = []
        self._visible: List[PaletteAction] = []
        self._selected = 0

        rect = NSMakeRect(0, 0, WIDTH, HEIGHT)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskFullSizeContentView
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setTitleVisibility_(NSWindowTitleHidden)
        self.window.setLevel_(NSFloatingWindowLevel)
        # Keep the single window instance alive across hide/show cycles —
        # we reuse it (see show()) rather than making a new one per search.
        self.window.setReleasedWhenClosed_(False)

        content = self.window.contentView()

        self.search_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, HEIGHT - 44, WIDTH - 24, 28)
        )
        self.search_field.setFont_(NSFont.systemFontOfSize_(18))
        self.search_field.setBezeled_(False)
        self.search_field.setDrawsBackground_(False)
        self.search_field.setPlaceholderString_("Search projects…")
        content.addSubview_(self.search_field)

        self.results_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, 12, WIDTH - 24, HEIGHT - 68)
        )
        self.results_field.setEditable_(False)
        self.results_field.setSelectable_(False)
        self.results_field.setBezeled_(False)
        self.results_field.setDrawsBackground_(False)
        self.results_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(13, 0))
        content.addSubview_(self.results_field)

        self._delegate = _Delegate.alloc().initWithPalette_(self)
        self.search_field.setDelegate_(self._delegate)

    # ---------- showing / dismissing ----------

    def show(self, actions: List[PaletteAction]) -> None:
        self._all_actions = actions
        self.search_field.setStringValue_("")
        self._selected = 0
        self._recompute()
        self._center_on_screen()
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.search_field)

    def _center_on_screen(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        sf = screen.frame()
        x = sf.origin.x + (sf.size.width - WIDTH) / 2
        y = sf.origin.y + sf.size.height * 0.65 - HEIGHT / 2
        self.window.setFrameOrigin_((x, y))

    def _dismiss(self) -> None:
        self.window.orderOut_(None)

    # ---------- filtering / selection (all plain Python, all testable) ----------

    def _on_query_changed(self) -> None:
        self._selected = 0
        self._recompute()

    def _recompute(self) -> None:
        query = str(self.search_field.stringValue())
        self._visible = filter_actions(self._all_actions, query)
        if self._selected >= len(self._visible):
            self._selected = max(0, len(self._visible) - 1)
        self._render_rows()

    def _move_selection(self, delta: int) -> None:
        if not self._visible:
            return
        self._selected = (self._selected + delta) % len(self._visible)
        self._render_rows()

    def _render_rows(self) -> None:
        if not self._visible:
            self.results_field.setStringValue_("No matching projects.")
            return
        lines = [a.label for a in self._visible[:VISIBLE_ROWS]]
        text = NSMutableAttributedString.alloc().initWithString_("\n".join(lines))
        pos = 0
        for i, line in enumerate(lines):
            if i == self._selected:
                text.addAttribute_value_range_(
                    NSBackgroundColorAttributeName,
                    NSColor.selectedTextBackgroundColor(),
                    (pos, len(line)),
                )
            pos += len(line) + 1  # +1 for the newline joining lines
        self.results_field.setAttributedStringValue_(text)

    def _run_selected(self) -> None:
        if not self._visible:
            return
        action = self._visible[self._selected]
        self._dismiss()
        self._on_run(action)

    # ---------- test hooks ----------
    # Exposed as plain methods (not underscored) so tests can drive the
    # palette the same way real keystrokes would, without needing a live
    # NSApp run loop or synthesizing actual NSEvents.

    def type_query(self, text: str) -> None:
        self.search_field.setStringValue_(text)
        self._on_query_changed()

    def press_down(self) -> None:
        self._move_selection(1)

    def press_up(self) -> None:
        self._move_selection(-1)

    def press_enter(self) -> None:
        self._run_selected()

    def press_escape(self) -> None:
        self._dismiss()

    @property
    def visible_actions(self) -> List[PaletteAction]:
        return list(self._visible)

    @property
    def selected_index(self) -> int:
        return self._selected
