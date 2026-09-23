// Pure helpers for the weekly note layout. Kept free of the Joplin API so
// they can be unit-tested with jest.
//
// Layout under the chosen root notebook:
//   <Root>/2026/09 - September/2026-09-07
// where the note title is the Monday of the week, the Year/Month notebooks
// come from that Monday, and the body uses the same "# YYYY-MM-DD" day
// headers and "- [prefix] text" entries as the standalone app's .md files.

const MONTH_NAMES = [
	'January', 'February', 'March', 'April', 'May', 'June',
	'July', 'August', 'September', 'October', 'November', 'December',
];

const DAY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function parseDay(day: string): Date {
	const match = DAY_PATTERN.exec(day);
	if (!match) throw new Error(`Invalid day "${day}", expected YYYY-MM-DD`);
	// UTC avoids DST shifts when doing whole-day arithmetic.
	return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function formatDay(date: Date): string {
	const mm = String(date.getUTCMonth() + 1).padStart(2, '0');
	const dd = String(date.getUTCDate()).padStart(2, '0');
	return `${date.getUTCFullYear()}-${mm}-${dd}`;
}

// Local calendar day for a Date, as YYYY-MM-DD.
export function localDay(date: Date = new Date()): string {
	const mm = String(date.getMonth() + 1).padStart(2, '0');
	const dd = String(date.getDate()).padStart(2, '0');
	return `${date.getFullYear()}-${mm}-${dd}`;
}

// Monday of the ISO week containing `day` (YYYY-MM-DD in, YYYY-MM-DD out).
export function mondayOf(day: string): string {
	const date = parseDay(day);
	// getUTCDay(): Sunday is 0, Monday is 1
	const offset = (date.getUTCDay() + 6) % 7;
	date.setUTCDate(date.getUTCDate() - offset);
	return formatDay(date);
}

export interface WeekLocation {
	year: string; // Year notebook title, e.g. "2026"
	month: string; // Month notebook title, e.g. "09 - September"
	title: string; // Weekly note title, e.g. "2026-09-07"
}

// Where the entry for `day` belongs. A week spanning two months is filed
// under the month of its Monday.
export function weekLocation(day: string): WeekLocation {
	const monday = mondayOf(day);
	const date = parseDay(monday);
	const monthIndex = date.getUTCMonth();
	return {
		year: String(date.getUTCFullYear()),
		month: `${String(monthIndex + 1).padStart(2, '0')} - ${MONTH_NAMES[monthIndex]}`,
		title: monday,
	};
}

function escapeRegExp(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Insert `entryLine` under the "# day" header of a weekly note body. Ported
// from the section insertion in storage.py:append_note so both produce
// identical markdown.
export function insertEntry(body: string, day: string, entryLine: string): string {
	if (!body.trim()) {
		return `# ${day}\n\n${entryLine}\n`;
	}

	const dayHeader = `# ${day}`;
	const headerMatches = Array.from(body.matchAll(new RegExp(`^#\\s+${escapeRegExp(day)}\\s*$`, 'gm')));

	if (!headerMatches.length) {
		// No header for this day yet: append at the bottom
		const separator = body.endsWith('\n\n') ? '' : (body.endsWith('\n') ? '\n' : '\n\n');
		return `${body}${separator}${dayHeader}\n\n${entryLine}\n`;
	}

	// Day header exists: append under it, before the next day header (if any)
	const match = headerMatches[headerMatches.length - 1];
	const startIdx = match.index + match[0].length;
	const nextHeader = /^#\s+\d{4}-\d{2}-\d{2}/m.exec(body.slice(startIdx));
	if (nextHeader) {
		const insertPos = startIdx + nextHeader.index;
		const section = body.slice(startIdx, insertPos).trimEnd();
		const replacement = section ? `${section}\n${entryLine}\n\n` : `\n\n${entryLine}\n\n`;
		return body.slice(0, startIdx) + replacement + body.slice(insertPos);
	}

	// This day is the last section of the note
	return `${body.trimEnd()}\n${entryLine}\n`;
}
