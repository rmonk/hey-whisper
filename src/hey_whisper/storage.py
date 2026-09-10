"""Storage manager for spoken notes in weekly Markdown files.

File naming:
  spoken-notes-YYYY-MM-DD.md
  where YYYY-MM-DD is the date of the first note recorded in that week.

Formatting:
  Items separated by day with headers: # YYYY-MM-DD
  Timestamps: YYYY-MM-DD HH:MM TZ
  Entries: - [YYYY-MM-DD HH:MM TZ] Transcribed content
"""

from datetime import datetime, date, timedelta
from pathlib import Path
import re
from typing import Optional, Dict, List, Tuple


FILENAME_PREFIX = "spoken-notes-"
FILENAME_SUFFIX = ".md"
DATE_PATTERN = re.compile(r"^spoken-notes-(\d{4}-\d{2}-\d{2})\.md$")
DAY_HEADER_PATTERN = re.compile(r"^#\s+(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


DEFAULT_NOTE_PREFIX = "[%Y-%m-%d %H:%M %Z]"


def format_timestamp(dt: Optional[datetime] = None) -> Tuple[str, str, str]:
    """Return (day_str, time_str, full_timestamp_str).
    
    Format: YYYY-MM-DD HH:MM TZ
    Example: ('2026-09-09', '12:08 EDT', '2026-09-09 12:08 EDT')
    """
    if dt is None:
        dt = datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.astimezone()

    tz_str = dt.strftime("%Z")
    if not tz_str:
        tz_str = dt.strftime("%z")

    day_str = dt.strftime("%Y-%m-%d")
    timestamp_str = dt.strftime(f"%Y-%m-%d %H:%M {tz_str}").strip()
    return day_str, dt.strftime(f"%H:%M {tz_str}").strip(), timestamp_str


def format_note_prefix(template: Optional[str] = None, dt: Optional[datetime] = None) -> str:
    """Format note prefix string supporting standard strftime codes and YYYY-MM-DD aliases.
    
    Default: [YYYY-MM-DD HH:MM TZ] via '[%Y-%m-%d %H:%M %Z]'
    """
    if dt is None:
        dt = datetime.now().astimezone()
    elif dt.tzinfo is None:
        dt = dt.astimezone()

    tz_str = dt.strftime("%Z")
    if not tz_str:
        tz_str = dt.strftime("%z")

    raw_tpl = template if template and template.strip() else DEFAULT_NOTE_PREFIX

    # Convert common human-readable date/time variables if present without %
    expanded = raw_tpl
    if "TZ" in expanded:
        expanded = expanded.replace("TZ", tz_str)
    if "YYYY" in expanded:
        expanded = expanded.replace("YYYY", "%Y")
    if "DD" in expanded:
        expanded = expanded.replace("DD", "%d")
    if "HH" in expanded:
        expanded = expanded.replace("HH", "%H")
    # Convert :MM in time and -MM- in date
    expanded = re.sub(r':MM\b', ':%M', expanded)
    expanded = re.sub(r'\bMM-', '%m-', expanded)
    expanded = re.sub(r'-MM\b', '-%m', expanded)
    expanded = re.sub(r'/MM\b', '/%m', expanded)

    # Format using standard strftime
    try:
        formatted = dt.strftime(expanded)
    except Exception:
        formatted = dt.strftime(f"[%Y-%m-%d %H:%M {tz_str}]")

    return formatted.strip()


def format_entry_line(
    text: str,
    prefix_template: Optional[str] = None,
    dt: Optional[datetime] = None,
) -> str:
    """Format full entry line for a note, ensuring markdown list bullet structure."""
    cleaned = text.strip()
    prefix = format_note_prefix(prefix_template, dt)

    if re.match(r"^(\s*[-*+]|\s*\d+\.|\s*>)", prefix):
        return f"{prefix} {cleaned}"
    else:
        return f"- {prefix} {cleaned}"



def get_week_bounds(target_date: date) -> Tuple[date, date]:
    """Return (monday_date, sunday_date) for the ISO week containing target_date."""
    # weekday(): Monday is 0, Sunday is 6
    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def find_existing_weekly_file(notes_dir: Path, target_date: date) -> Optional[Path]:
    """Find an existing weekly note file whose filename date falls in the same calendar week."""
    if not notes_dir.is_dir():
        return None

    monday, sunday = get_week_bounds(target_date)

    matching_files = []
    for file_path in notes_dir.glob(f"{FILENAME_PREFIX}*{FILENAME_SUFFIX}"):
        match = DATE_PATTERN.match(file_path.name)
        if match:
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if monday <= file_date <= sunday:
                    matching_files.append((file_date, file_path))
            except ValueError:
                continue

    if not matching_files:
        return None

    # Return the file with earliest creation date for this week
    matching_files.sort(key=lambda x: x[0])
    return matching_files[0][1]


def get_weekly_file_path(notes_dir: Path, target_date: Optional[date] = None) -> Path:
    """Resolve the path to the weekly file for target_date.
    
    If a file for the week already exists, returns its path.
    Otherwise returns path for a new file named with target_date.
    """
    if target_date is None:
        target_date = datetime.now().astimezone().date()

    existing = find_existing_weekly_file(notes_dir, target_date)
    if existing is not None:
        return existing

    filename = f"{FILENAME_PREFIX}{target_date.strftime('%Y-%m-%d')}{FILENAME_SUFFIX}"
    return notes_dir / filename


def append_note(
    notes_dir: Path,
    text: str,
    timestamp: Optional[datetime] = None,
    prefix_template: Optional[str] = None,
) -> Tuple[Path, str]:
    """Append a spoken note to the appropriate weekly markdown file.
    
    Returns (file_path, formatted_entry_line).
    """
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("Note text cannot be empty.")

    if timestamp is None:
        timestamp = datetime.now().astimezone()
    elif timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()

    day_str = timestamp.strftime("%Y-%m-%d")
    target_date = timestamp.date()

    notes_dir.mkdir(parents=True, exist_ok=True)
    file_path = get_weekly_file_path(notes_dir, target_date)

    entry_line = format_entry_line(cleaned_text, prefix_template, timestamp)

    if not file_path.exists():
        # New weekly file: start with day header and first note
        content = f"# {day_str}\n\n{entry_line}\n"
        file_path.write_text(content, encoding="utf-8")
        return file_path, entry_line

    content = file_path.read_text(encoding="utf-8")

    # Check if this day's header exists in the file
    day_header = f"# {day_str}"
    header_matches = list(re.finditer(rf"^#\s+{re.escape(day_str)}\s*$", content, re.MULTILINE))

    if not header_matches:
        # Header does not exist yet for this day: append at bottom
        separator = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        new_content = f"{content}{separator}{day_header}\n\n{entry_line}\n"
    else:
        # Day header exists. Locate next day header or end of file to append item under this day
        match = header_matches[-1]
        start_idx = match.end()
        # Find next header (# ...) after this day
        next_header = re.search(r"^#\s+\d{4}-\d{2}-\d{2}", content[start_idx:], re.MULTILINE)
        if next_header:
            insert_pos = start_idx + next_header.start()
            section = content[start_idx:insert_pos].rstrip()
            if not section:
                replacement = f"\n\n{entry_line}\n\n"
            else:
                replacement = f"{content[start_idx:insert_pos].rstrip()}\n{entry_line}\n\n"
            new_content = content[:start_idx] + replacement + content[insert_pos:]
        else:
            # Current day is the last section in the file
            stripped = content.rstrip()
            new_content = f"{stripped}\n{entry_line}\n"

    file_path.write_text(new_content, encoding="utf-8")
    return file_path, entry_line


def list_note_files(notes_dir: Path) -> List[Path]:
    """List all weekly note markdown files in the notes directory, sorted newest first."""
    if not notes_dir.is_dir():
        return []

    files = []
    for f in notes_dir.glob(f"{FILENAME_PREFIX}*{FILENAME_SUFFIX}"):
        match = DATE_PATTERN.match(f.name)
        if match:
            files.append(f)

    # Sort descending by filename date
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def group_files_by_year_month(notes_dir: Path) -> Dict[int, Dict[int, List[Path]]]:
    """Group weekly note files by Year -> Month -> List[Path].
    
    Structure:
      {
        2026: {
          9: [Path('spoken-notes-2026-09-09.md'), ...],
          8: [...]
        }
      }
    """
    grouped: Dict[int, Dict[int, List[Path]]] = {}
    for file_path in list_note_files(notes_dir):
        match = DATE_PATTERN.match(file_path.name)
        if not match:
            continue
        try:
            d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue

        year = d.year
        month = d.month
        if year not in grouped:
            grouped[year] = {}
        if month not in grouped[year]:
            grouped[year][month] = []
        grouped[year][month].append(file_path)

    return grouped


def get_file_days(file_path: Path) -> List[str]:
    """Extract all day headers (# YYYY-MM-DD) from a markdown file."""
    if not file_path.is_file():
        return []
    content = file_path.read_text(encoding="utf-8", errors="replace")
    return DAY_HEADER_PATTERN.findall(content)
