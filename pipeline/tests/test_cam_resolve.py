"""The cam-resolver's safety rule (tools/cam-scan/scan.py).

A cam usually "dies" without anyone touching it - YouTube rotates the video id when a 24/7
stream restarts - so the repair is a pure id swap. The danger is that a channel's OTHER live
stream is a different beach, not a new angle on the same one. Auto-taking the channel's first
live stream proposed Miura's cam as Chigasaki's replacement: 30 km away and already assigned
to another spot (CALIBRATION-adjacent note, CLAUDE.md 2026-07-29).

These pin the rule that stops that, since the failure is invisible in a diff - a wrong swap
looks exactly like a routine one.

Loaded by path: scan.py is a standalone tool, not part of the rosa_pipeline package. Its
module-level code is imports + constants only, so importing it touches no network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "cam-scan" / "scan.py"
_spec = importlib.util.spec_from_file_location("cam_scan", SCRIPT)
assert _spec and _spec.loader
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)


def _item(vid: str, title: str) -> dict:
    return {"id": {"videoId": vid}, "snippet": {"title": title}}


CHIGASAKI = "【LIVE】茅ヶ崎サザンビーチライブカメラ(Live Camera in Chigasaki Southern Beach)"
MIURA = "【LIVE】三浦海岸ライブカメラ(Live Camera in Miura Beach)"


def test_same_title_is_the_same_camera_and_is_applied() -> None:
    """The routine case: a 24/7 stream restarted under a new id."""
    match, why = scan.pick_replacement(CHIGASAKI, [_item("NEW123", CHIGASAKI)], set())
    assert match is not None and match["id"]["videoId"] == "NEW123"
    assert "same title" in why


def test_a_different_beach_on_the_same_channel_is_refused() -> None:
    """The actual 2026-07-29 incident: WITH SEA's live stream was Miura, not Chigasaki."""
    match, why = scan.pick_replacement(CHIGASAKI, [_item("49NubJ78KWU", MIURA)], set())
    assert match is None
    assert "no title match" in why


def test_a_stream_already_assigned_elsewhere_is_never_stolen() -> None:
    """Even an exact title match must not duplicate one camera across two spots."""
    match, why = scan.pick_replacement(CHIGASAKI, [_item("TAKEN1", CHIGASAKI)], {"TAKEN1"})
    assert match is None
    assert "no unassigned" in why


def test_the_matching_stream_is_found_even_when_it_is_not_first() -> None:
    """The old code took items[0]; the right stream may be anywhere in the channel's list."""
    items = [_item("OTHER1", MIURA), _item("OTHER2", "江の島"), _item("RIGHT", CHIGASAKI)]
    match, _ = scan.pick_replacement(CHIGASAKI, items, set())
    assert match is not None and match["id"]["videoId"] == "RIGHT"


def test_live_badge_noise_does_not_block_a_match() -> None:
    """Broadcasters add and drop 【LIVE】/red-dot/24H at will; it names no beach."""
    match, _ = scan.pick_replacement(
        "【LIVE】茅ヶ崎サザンビーチライブカメラ",
        [_item("NEW", "🔴 茅ヶ崎サザンビーチライブカメラ 24H")],
        set(),
    )
    assert match is not None


def test_html_entities_in_a_title_still_match() -> None:
    """The live API returns &quot; in titles (seen on the hagolshim stream)."""
    match, _ = scan.pick_replacement(
        'חוף הגולשים ראשל"צ', [_item("NEW", "חוף הגולשים ראשל&quot;צ")], set()
    )
    assert match is not None


def test_a_deleted_stream_leaves_no_title_to_match_so_a_human_decides() -> None:
    match, why = scan.pick_replacement(None, [_item("NEW", CHIGASAKI)], set())
    assert match is None
    assert "cannot match" in why


def test_no_candidates_at_all() -> None:
    match, why = scan.pick_replacement(CHIGASAKI, [], set())
    assert match is None
    assert "no unassigned" in why
