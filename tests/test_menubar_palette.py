"""Tests for the search/command palette's custom AppKit window. Skipped
entirely when the optional `menubar` extra (rumps/pyobjc) isn't installed —
same convention as the other menubar test files, even though this module
only imports AppKit/Foundation directly, never rumps itself."""

import pytest

pytest.importorskip("rumps")

from pathlib import Path

from collaborate.menubar_model import ProjectEntry, palette_actions
from collaborate.menubar_palette import SearchPalette


def _entries():
    return [
        ProjectEntry("Ep01_RoughCut", Path("Ep01.prproj"), "mine", None, None, 0, False),
        ProjectEntry("Ep02_Assembly", Path("Ep02.prproj"), "available", None, None, 1, False),
        ProjectEntry("Brand_Sizzle", Path("Brand.prproj"), "available", None, None, 0, False),
    ]


def test_show_populates_visible_actions_and_resets_selection():
    palette = SearchPalette(on_run=lambda a: None)
    palette.show(palette_actions(_entries()))

    assert [a.label for a in palette.visible_actions] == [
        "Check in — Ep01_RoughCut",
        "Add note — Ep01_RoughCut",
        "Check out — Ep02_Assembly",
        "Check out — Brand_Sizzle",
    ]
    assert palette.selected_index == 0


def test_typing_filters_and_resets_selection():
    palette = SearchPalette(on_run=lambda a: None)
    palette.show(palette_actions(_entries()))

    palette.press_down()
    assert palette.selected_index == 1

    palette.type_query("brand")
    assert [a.project for a in palette.visible_actions] == ["Brand_Sizzle"]
    assert palette.selected_index == 0, "filtering should reset the selection"


def test_arrow_keys_wrap_around():
    palette = SearchPalette(on_run=lambda a: None)
    palette.show(palette_actions(_entries()))

    assert palette.selected_index == 0
    palette.press_up()
    assert palette.selected_index == len(palette.visible_actions) - 1, "up from the top should wrap to the bottom"

    palette.press_down()
    assert palette.selected_index == 0, "down from the bottom should wrap to the top"


def test_enter_dismisses_and_runs_the_selected_action():
    runs = []
    palette = SearchPalette(on_run=lambda a: runs.append(a))
    palette.show(palette_actions(_entries()))

    palette.press_down()  # selects "Add note — Ep01_RoughCut"
    palette.press_enter()

    assert len(runs) == 1
    assert runs[0].verb == "Add note"
    assert runs[0].project == "Ep01_RoughCut"


def test_escape_dismisses_without_running_anything():
    runs = []
    palette = SearchPalette(on_run=lambda a: runs.append(a))
    palette.show(palette_actions(_entries()))

    palette.press_escape()
    assert runs == []


def test_no_matches_does_not_crash():
    palette = SearchPalette(on_run=lambda a: None)
    palette.show(palette_actions(_entries()))

    palette.type_query("this matches nothing at all")
    assert palette.visible_actions == []
    # selection/enter on an empty list must be a safe no-op, not a crash
    palette.press_down()
    palette.press_enter()


def test_reopening_resets_stale_filter_and_selection_state():
    palette = SearchPalette(on_run=lambda a: None)
    palette.show(palette_actions(_entries()))
    palette.type_query("brand")

    # a second open (e.g. after a refresh picked up a new project) must not
    # carry over the previous session's filter text or selected index
    new_entries = _entries() + [
        ProjectEntry("Ep04_VFX", Path("Ep04.prproj"), "available", None, None, 0, False)
    ]
    palette.show(palette_actions(new_entries))

    assert len(palette.visible_actions) == 5
    assert palette.selected_index == 0
