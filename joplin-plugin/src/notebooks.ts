// Resolves and creates the Root > Year > Month notebooks and weekly notes
// through the Joplin data API.

import joplin from 'api';
import { insertEntry, weekLocation } from './weekly';

interface Folder {
	id: string;
	title: string;
	parent_id: string;
}

interface Note {
	id: string;
	title: string;
}

async function fetchAll<T>(path: string[], fields: string[]): Promise<T[]> {
	const items: T[] = [];
	let page = 1;
	let result;
	do {
		result = await joplin.data.get(path, { fields, page, limit: 100 });
		items.push(...result.items);
		page++;
	} while (result.has_more);
	return items;
}

export async function getFolder(id: string): Promise<Folder | null> {
	if (!id) return null;
	try {
		return await joplin.data.get(['folders', id], { fields: ['id', 'title', 'parent_id'] });
	} catch (error) {
		return null; // Deleted notebook
	}
}

async function findFolder(parentId: string, title: string): Promise<Folder | null> {
	const folders = await fetchAll<Folder>(['folders'], ['id', 'title', 'parent_id']);
	return folders.find(f => f.parent_id === parentId && f.title === title) || null;
}

async function ensureFolder(parentId: string, title: string): Promise<Folder> {
	const existing = await findFolder(parentId, title);
	if (existing) return existing;
	return await joplin.data.post(['folders'], null, { title, parent_id: parentId });
}

async function findNote(folderId: string, title: string): Promise<Note | null> {
	const notes = await fetchAll<Note>(['folders', folderId, 'notes'], ['id', 'title']);
	return notes.find(n => n.title === title) || null;
}

export interface WeekNote {
	id: string;
	title: string;
	created: boolean;
}

// Find the weekly note for `day`. With create=false, returns null instead of
// creating missing notebooks or the note.
export async function resolveWeekNote(rootId: string, day: string, create: boolean): Promise<WeekNote | null> {
	const loc = weekLocation(day);
	if (!create) {
		const year = await findFolder(rootId, loc.year);
		const month = year && await findFolder(year.id, loc.month);
		const note = month && await findNote(month.id, loc.title);
		return note ? { id: note.id, title: note.title, created: false } : null;
	}

	const year = await ensureFolder(rootId, loc.year);
	const month = await ensureFolder(year.id, loc.month);
	const note = await findNote(month.id, loc.title);
	if (note) return { id: note.id, title: note.title, created: false };
	const created = await joplin.data.post(['notes'], null, { title: loc.title, parent_id: month.id, body: '' });
	return { id: created.id, title: loc.title, created: true };
}

// Writes are serialized so two quick transcripts can't read the same body
// and overwrite each other.
let queue: Promise<unknown> = Promise.resolve();

export function appendEntry(rootId: string, day: string, entryLine: string): Promise<WeekNote> {
	const task = queue.then(async () => {
		const week = await resolveWeekNote(rootId, day, true);
		const note = await joplin.data.get(['notes', week.id], { fields: ['id', 'body'] });
		await joplin.data.put(['notes', week.id], null, { body: insertEntry(note.body || '', day, entryLine) });
		return week;
	});
	queue = task.catch(() => undefined);
	return task;
}
