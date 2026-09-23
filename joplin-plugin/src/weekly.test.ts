import { insertEntry, localDay, mondayOf, weekLocation } from './weekly';

describe('mondayOf', () => {
	test.each([
		['2026-09-07', '2026-09-07'], // Monday
		['2026-09-09', '2026-09-07'], // Wednesday
		['2026-09-13', '2026-09-07'], // Sunday
		['2026-09-14', '2026-09-14'], // next Monday
		['2027-01-01', '2026-12-28'], // crosses a year
		['2026-03-08', '2026-03-02'], // US DST starts
		['2026-11-01', '2026-10-26'], // US DST ends
	])('%s -> %s', (day, monday) => {
		expect(mondayOf(day)).toBe(monday);
	});

	test('rejects malformed days', () => {
		expect(() => mondayOf('2026-9-9')).toThrow();
	});
});

describe('weekLocation', () => {
	test('files the week under its Monday', () => {
		expect(weekLocation('2026-09-11')).toEqual({ year: '2026', month: '09 - September', title: '2026-09-07' });
	});

	test('a week spanning two months goes under the Monday\'s month', () => {
		// Monday 2026-08-31, Thursday 2026-09-03
		expect(weekLocation('2026-09-03')).toEqual({ year: '2026', month: '08 - August', title: '2026-08-31' });
	});

	test('a week spanning two years goes under the Monday\'s year', () => {
		expect(weekLocation('2027-01-02')).toEqual({ year: '2026', month: '12 - December', title: '2026-12-28' });
	});
});

describe('localDay', () => {
	test('formats the local calendar date', () => {
		expect(localDay(new Date(2026, 8, 9, 23, 59))).toBe('2026-09-09');
	});
});

// Expected bodies were generated with storage.py:append_note (prefix "none")
// so the Joplin plugin writes byte-identical markdown to the standalone app.
describe('insertEntry matches storage.py:append_note', () => {
	test('builds a week note one entry at a time', () => {
		const steps: [string, string, string][] = [
			['2026-09-09', '- a', '# 2026-09-09\n\n- a\n'],
			['2026-09-09', '- b', '# 2026-09-09\n\n- a\n- b\n'],
			['2026-09-11', '- c', '# 2026-09-09\n\n- a\n- b\n\n# 2026-09-11\n\n- c\n'],
			['2026-09-09', '- d', '# 2026-09-09\n\n- a\n- b\n- d\n\n# 2026-09-11\n\n- c\n'],
			['2026-09-11', '- e', '# 2026-09-09\n\n- a\n- b\n- d\n\n# 2026-09-11\n\n- c\n- e\n'],
		];
		let body = '';
		for (const [day, entry, expected] of steps) {
			body = insertEntry(body, day, entry);
			expect(body).toBe(expected);
		}
	});

	test.each([
		['# 2026-09-09\n\n- a', '2026-09-10', '# 2026-09-09\n\n- a\n\n# 2026-09-10\n\n- z\n'],
		['# 2026-09-09\n\n- a\n', '2026-09-10', '# 2026-09-09\n\n- a\n\n# 2026-09-10\n\n- z\n'],
		['# 2026-09-09\n\n# 2026-09-10\n\n- b\n', '2026-09-09', '# 2026-09-09\n\n\n- z\n\n# 2026-09-10\n\n- b\n'],
		['Intro text\n# 2026-09-09\n\n- a\n\n\n# 2026-09-10\n- b\n', '2026-09-09', 'Intro text\n# 2026-09-09\n\n- a\n- z\n\n# 2026-09-10\n- b\n'],
	])('hand-edited body %j on %s', (body, day, expected) => {
		expect(insertEntry(body, day, '- z')).toBe(expected);
	});

	test('whitespace-only body starts fresh', () => {
		expect(insertEntry('  \n', '2026-09-09', '- a')).toBe('# 2026-09-09\n\n- a\n');
	});
});
