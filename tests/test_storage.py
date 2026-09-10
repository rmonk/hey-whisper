"""Unit tests for storage.py."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from hey_whisper.storage import (
    get_week_bounds,
    get_weekly_file_path,
    append_note,
    list_note_files,
    group_files_by_year_month,
    get_file_days,
    format_timestamp,
    format_note_prefix,
    format_entry_line,
    DEFAULT_NOTE_PREFIX,
)


def test_format_timestamp():
    # 2026-09-09 12:00 UTC
    dt = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    day_str, time_str, full_ts = format_timestamp(dt)
    assert day_str == "2026-09-09"
    assert "2026-09-09 12:00" in full_ts
    assert "UTC" in full_ts or "+0000" in full_ts


def test_get_week_bounds():
    # 2026-09-09 is Wednesday
    wed = datetime(2026, 9, 9).date()
    mon, sun = get_week_bounds(wed)
    assert mon.strftime("%Y-%m-%d") == "2026-09-07"  # Monday
    assert sun.strftime("%Y-%m-%d") == "2026-09-13"  # Sunday


def test_weekly_file_naming_rule(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    wed = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    thu = datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc)
    next_mon = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)

    # First note of week is on Wednesday -> file must be named spoken-notes-2026-09-09.md
    f1, entry1 = append_note(notes_dir, "Wednesday initial note", wed)
    assert f1.name == "spoken-notes-2026-09-09.md"
    assert "Wednesday initial note" in f1.read_text()
    assert "# 2026-09-09" in f1.read_text()

    # Second note on Thursday in same week -> must append to same file!
    f2, entry2 = append_note(notes_dir, "Thursday note", thu)
    assert f2 == f1
    content = f2.read_text()
    assert "# 2026-09-09" in content
    assert "# 2026-09-10" in content
    assert "Thursday note" in content

    # Note in next week -> new file created for that week
    f3, entry3 = append_note(notes_dir, "Next week note", next_mon)
    assert f3.name == "spoken-notes-2026-09-14.md"
    assert f3 != f1


def test_multiple_notes_same_day(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    dt1 = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)

    f, _ = append_note(notes_dir, "First note", dt1)
    append_note(notes_dir, "Second note", dt2)

    content = f.read_text()
    # The day header should appear only once
    assert content.count("# 2026-09-09") == 1
    assert "First note" in content
    assert "Second note" in content
    assert content.count("- [2026-09-09") == 2


def test_group_files_by_year_month(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    d1 = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    d3 = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)

    append_note(notes_dir, "Note in August", d1)
    append_note(notes_dir, "Note in Sep week 1", d2)
    append_note(notes_dir, "Note in Sep week 2", d3)

    grouped = group_files_by_year_month(notes_dir)
    assert 2026 in grouped
    assert 8 in grouped[2026]
    assert 9 in grouped[2026]
    assert len(grouped[2026][8]) == 1
    assert len(grouped[2026][9]) == 2


def test_get_file_days(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    d1 = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)

    f, _ = append_note(notes_dir, "Day 1", d1)
    append_note(notes_dir, "Day 2", d2)

    days = get_file_days(f)
    assert days == ["2026-09-09", "2026-09-10"]


def test_format_note_prefix_defaults():
    dt = datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)
    # Default prefix format
    p1 = format_note_prefix(None, dt)
    assert p1.startswith("[2026-09-09 14:30")
    assert p1.endswith("]")

    p2 = format_note_prefix(DEFAULT_NOTE_PREFIX, dt)
    assert p2 == p1


def test_format_note_prefix_custom_variables():
    dt = datetime(2026, 9, 9, 14, 30, 45, tzinfo=timezone.utc)
    # Standard strftime variables
    res = format_note_prefix("[%Y/%m/%d %H:%M:%S]", dt)
    assert res == "[2026/09/09 14:30:45]"

    # 12-hour AM/PM format
    res_12h = format_note_prefix("[%I:%M %p]", dt)
    assert res_12h == "[02:30 PM]"

    # Human-readable alias format [YYYY-MM-DD HH:MM TZ]
    res_alias = format_note_prefix("[YYYY-MM-DD HH:MM TZ]", dt)
    assert "2026-09-09 14:30" in res_alias


def test_append_note_with_custom_prefix(tmp_path: Path):
    notes_dir = tmp_path / "notes"
    dt = datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)

    # Note with custom prefix format
    f, entry = append_note(
        notes_dir,
        "Custom prefix note",
        timestamp=dt,
        prefix_template="* [%H:%M]",
    )
    assert entry == "* [14:30] Custom prefix note"
    assert "* [14:30] Custom prefix note" in f.read_text()

    # Note without explicit bullet in template should get '- '
    f2, entry2 = append_note(
        notes_dir,
        "Another note",
        timestamp=dt,
        prefix_template="[%H:%M:%S]",
    )
    assert entry2 == "- [14:30:00] Another note"
    assert "- [14:30:00] Another note" in f2.read_text()

