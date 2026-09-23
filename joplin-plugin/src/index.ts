import joplin from 'api';
import { MenuItemLocation, SettingItemType, ToastType, ToolbarButtonLocation } from 'api/types';
import { Sidecar, SidecarEvent, splitCommand } from './sidecar';
import { resolveCommand } from './resolveCommand';
import { appendEntry, getFolder, resolveWeekNote } from './notebooks';
import { localDay } from './weekly';

const SECTION = 'heyWhisper';
const SETTING_ROOT = 'heyWhisper.rootFolderId';
const SETTING_MODE = 'heyWhisper.mode';
const SETTING_COMMAND = 'heyWhisper.sidecarCommand';
const SETTING_PANEL_VISIBLE = 'heyWhisper.panelVisible';

const TOGGLE_ACCELERATOR = 'CmdOrCtrl+Shift+Space';
const CANCEL_ACCELERATOR = 'CmdOrCtrl+Shift+Backspace';
// For pop-up text; matches the default accelerators above
const MOD_KEY = process.platform === 'darwin' ? 'Cmd' : 'Ctrl';

type Mode = 'hold' | 'toggle' | 'silence';

// Everything the panel needs to render, pushed to it after every change.
interface PanelState {
	type: 'state';
	status: 'idle' | 'starting' | 'recording' | 'transcribing';
	mode: Mode;
	backend: string;
	model: string;
	command: string;
	rootTitle: string;
	lastEntry: string;
	lastNote: string;
	message: string;
	messageKind: 'info' | 'error' | '';
}

const state: PanelState = {
	type: 'state',
	status: 'idle',
	mode: 'hold',
	backend: '',
	model: '',
	command: '',
	rootTitle: '',
	lastEntry: '',
	lastNote: '',
	message: '',
	messageKind: '',
};

let panel: string;
let sidecar: Sidecar;
let recording = false;
// A start command has been sent but the engine hasn't confirmed (or refused) it
// yet. The engine may still be launching, so this can last several seconds.
let startPending = false;
let pendingTranscripts = 0;
let rootId = '';

function refreshStatus() {
	if (recording) state.status = 'recording';
	else if (pendingTranscripts > 0) state.status = 'transcribing';
	else if (state.status !== 'starting') state.status = 'idle';
}

function pushState() {
	refreshStatus();
	if (panel) joplin.views.panels.postMessage(panel, state);
}

function setMessage(message: string, kind: 'info' | 'error' | '' = 'info') {
	state.message = message;
	state.messageKind = kind;
}

// Pop-up message, shown only while the panel is hidden (the panel shows state.message).
async function notify(message: string, type: ToastType = ToastType.Info, duration = 3000) {
	if (panel && await joplin.views.panels.visible(panel)) return;
	await joplin.views.dialogs.showToast({ message, type, duration });
}

async function notifyError(message: string) {
	setMessage(message, 'error');
	pushState();
	await notify(`Hey Whisper: ${message}`, ToastType.Error, 6000);
}

function truncate(text: string, max: number): string {
	return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

async function loadRoot() {
	rootId = await joplin.settings.value(SETTING_ROOT);
	const folder = await getFolder(rootId);
	if (!folder) rootId = '';
	state.rootTitle = folder ? folder.title : '';
}

// An explicit command in settings wins; otherwise find an installed Hey Whisper.
async function sidecarArgv(): Promise<string[]> {
	const configured = ((await joplin.settings.value(SETTING_COMMAND)) || '').trim();
	if (configured) return splitCommand(configured);

	const resolved = await resolveCommand();
	if (!resolved) {
		throw new Error(
			'Hey Whisper was not found in ~/.local/bin, on PATH, or as a Flatpak. '
			+ 'Install it, or set the command in Tools > Options > Hey Whisper.',
		);
	}
	return resolved.argv;
}

async function requireRoot(): Promise<boolean> {
	await loadRoot();
	if (rootId) return true;
	await joplin.views.dialogs.showMessageBox(
		'Hey Whisper needs a notebook to write into.\n\n'
		+ 'Select the notebook in the sidebar, then run Tools > Hey Whisper > Use selected notebook for voice notes.',
	);
	return false;
}

async function handleSidecarEvent(evt: SidecarEvent) {
	switch (evt.event) {
	case 'starting':
		state.status = 'starting';
		state.command = evt.command;
		setMessage('Starting the Hey Whisper engine…');
		void notify('Starting Hey Whisper…');
		break;
	case 'ready':
		state.status = 'idle';
		state.backend = evt.backend;
		state.model = evt.model;
		setMessage('');
		break;
	case 'recording':
		recording = true;
		startPending = false;
		setMessage(evt.mode === 'silence' ? 'Listening… stops when you pause.' : 'Recording…');
		void notify(
			evt.mode === 'silence'
				? `🎙️ Listening — stops when you pause (${MOD_KEY}+Shift+Backspace to cancel)`
				: `🎙️ Recording — click the mic or press ${MOD_KEY}+Shift+Space to finish, ${MOD_KEY}+Shift+Backspace to cancel`,
			ToastType.Info,
			4000,
		);
		break;
	case 'level':
		if (panel) joplin.views.panels.postMessage(panel, { type: 'level', rms: evt.rms, peak: evt.peak });
		return;
	case 'transcribing':
		recording = false;
		pendingTranscripts++;
		setMessage('Transcribing…');
		void notify('Transcribing…');
		break;
	case 'transcript':
		pendingTranscripts = Math.max(0, pendingTranscripts - 1);
		try {
			if (!rootId) throw new Error('No notebook chosen for voice notes.');
			const week = await appendEntry(rootId, evt.day, evt.entry_line);
			state.lastEntry = evt.entry_line;
			state.lastNote = week.title;
			setMessage(`Saved to ${state.rootTitle} › ${week.title}`);
			void notify(`Saved to ${state.rootTitle} › ${week.title}: ${truncate(evt.text, 80)}`, ToastType.Success, 5000);
		} catch (error) {
			// Don't lose the words: surface them so they can be pasted manually
			await notifyError(`Could not save note (${error.message}). Transcript: ${evt.text}`);
			return;
		}
		break;
	case 'empty':
		recording = false;
		pendingTranscripts = Math.max(0, pendingTranscripts - 1);
		setMessage(evt.reason || 'Nothing recorded.');
		void notify(state.message);
		break;
	case 'cancelled':
		recording = false;
		startPending = false;
		setMessage('Recording cancelled.');
		void notify(state.message, ToastType.Info, 2000);
		break;
	case 'status':
		recording = !!evt.recording;
		break;
	case 'error':
		recording = false;
		startPending = false;
		pendingTranscripts = 0;
		if (state.status === 'starting') state.status = 'idle';
		await notifyError(evt.message);
		return;
	case 'exited':
		recording = false;
		startPending = false;
		pendingTranscripts = 0;
		state.status = 'idle';
		if (evt.unexpected) {
			if (/unrecognized arguments: --serve/.test(evt.stderr || '')) {
				await notifyError(`The installed Hey Whisper (${state.command}) is too old for this plugin. Update it to a release with --serve support.`);
				return;
			}
			const detail = evt.stderr ? `\n${evt.stderr.split('\n').slice(-3).join('\n')}` : '';
			await notifyError(`The Hey Whisper engine stopped (exit code ${evt.code}).${detail}`);
			return;
		}
		break;
	}
	pushState();
}

async function startRecording(mode: Mode) {
	if (recording || startPending || !(await requireRoot())) return;
	startPending = true;
	// Hold mode is a manual stop, same as toggle, as far as the sidecar is concerned
	await sidecar.send({ cmd: 'start', mode: mode === 'silence' ? 'silence' : 'toggle' });
}

async function stopRecording() {
	// Also stop a start still in flight (e.g. hold released while the engine
	// launches). Sidecar.send keeps order, and the engine ignores a stop when idle.
	if (recording || startPending) await sidecar.send({ cmd: 'stop' });
}

async function cancelRecording() {
	if (recording || startPending) await sidecar.send({ cmd: 'cancel' });
}

async function toggleRecording() {
	if (recording || startPending) await stopRecording();
	else await startRecording(state.mode);
}

async function openThisWeek() {
	if (!(await requireRoot())) return;
	const week = await resolveWeekNote(rootId, localDay(), false);
	if (week) {
		await joplin.commands.execute('openNote', week.id);
	} else {
		await joplin.views.dialogs.showToast({ message: 'No voice notes this week yet.', type: ToastType.Info });
	}
}

async function useSelectedNotebook() {
	const folder = await joplin.workspace.selectedFolder();
	if (!folder) {
		await joplin.views.dialogs.showMessageBox('Select a notebook in the sidebar first.');
		return;
	}
	await joplin.settings.setValue(SETTING_ROOT, folder.id);
	await loadRoot();
	setMessage(`Voice notes will be saved under "${folder.title}".`);
	pushState();
	await notify(state.message, ToastType.Success);
}

async function setupPanel() {
	panel = await joplin.views.panels.create('heyWhisper.panel');
	await joplin.views.panels.setHtml(panel, '<div id="hey-whisper-root"></div>');
	await joplin.views.panels.addScript(panel, './panel/panel.css');
	await joplin.views.panels.addScript(panel, './panel/panel.js');
	await joplin.views.panels.onMessage(panel, async (msg: any) => {
		switch (msg.type) {
		case 'init':
			refreshStatus();
			return state;
		case 'toggle':
			await toggleRecording();
			break;
		case 'holdStart':
			await startRecording('hold');
			break;
		case 'holdEnd':
			await stopRecording();
			break;
		case 'cancel':
			await cancelRecording();
			break;
		case 'openWeek':
			await openThisWeek();
			break;
		case 'useSelectedNotebook':
			await useSelectedNotebook();
			break;
		}
		return null;
	});
	await joplin.views.panels.show(panel, await joplin.settings.value(SETTING_PANEL_VISIBLE));
}

joplin.plugins.register({
	onStart: async function() {
		await joplin.settings.registerSection(SECTION, {
			label: 'Hey Whisper',
			iconName: 'fas fa-microphone',
			description: 'Speech-to-text model and backend come from ~/.config/hey-whisper.conf, shared with the Hey Whisper app.',
		});
		await joplin.settings.registerSettings({
			[SETTING_MODE]: {
				section: SECTION,
				public: true,
				type: SettingItemType.String,
				isEnum: true,
				value: 'toggle',
				options: {
					hold: 'Hold: press and hold the panel button to talk (needs the panel)',
					toggle: 'Toggle: click to start, click again to finish',
					silence: 'Silence: stop automatically when you pause',
				},
				label: 'Recording mode',
				description: 'The mic button and keyboard shortcut always toggle (in Silence mode recording also stops when you pause).',
			},
			[SETTING_COMMAND]: {
				section: SECTION,
				public: true,
				type: SettingItemType.String,
				value: '',
				label: 'Hey Whisper command',
				description: 'Leave empty to detect it automatically: ~/.local/bin/hey-whisper, then hey-whisper on PATH, then the Hey Whisper Flatpak. '
					+ 'Or set a command that starts the engine, e.g. /path/to/hey-whisper --serve',
			},
			[SETTING_ROOT]: {
				section: SECTION,
				public: false,
				type: SettingItemType.String,
				value: '',
				label: 'Voice notes notebook ID',
			},
			[SETTING_PANEL_VISIBLE]: {
				section: SECTION,
				public: false,
				type: SettingItemType.Bool,
				value: false,
				label: 'Show the Hey Whisper panel',
			},
		});

		state.mode = await joplin.settings.value(SETTING_MODE);
		await loadRoot();

		sidecar = new Sidecar(sidecarArgv, evt => { void handleSidecarEvent(evt); });

		await joplin.settings.onChange(async event => {
			if (event.keys.includes(SETTING_MODE)) state.mode = await joplin.settings.value(SETTING_MODE);
			if (event.keys.includes(SETTING_COMMAND)) {
				recording = false;
				startPending = false;
				pendingTranscripts = 0;
				sidecar.restart();
			}
			pushState();
		});

		await joplin.commands.register({
			name: 'heyWhisper.toggleRecording',
			label: 'Hey Whisper: Start/stop voice note',
			iconName: 'fas fa-microphone',
			execute: toggleRecording,
		});
		await joplin.commands.register({
			name: 'heyWhisper.cancelRecording',
			label: 'Hey Whisper: Cancel recording',
			iconName: 'fas fa-times',
			execute: cancelRecording,
		});
		await joplin.commands.register({
			name: 'heyWhisper.openThisWeek',
			label: 'Hey Whisper: Open this week\'s voice notes',
			iconName: 'fas fa-calendar-week',
			execute: openThisWeek,
		});
		await joplin.commands.register({
			name: 'heyWhisper.useSelectedNotebook',
			label: 'Hey Whisper: Use selected notebook for voice notes',
			iconName: 'fas fa-folder',
			execute: useSelectedNotebook,
		});
		await joplin.commands.register({
			name: 'heyWhisper.togglePanel',
			label: 'Hey Whisper: Show/hide panel',
			iconName: 'fas fa-microphone',
			execute: async () => {
				const visible = !(await joplin.views.panels.visible(panel));
				await joplin.views.panels.show(panel, visible);
				await joplin.settings.setValue(SETTING_PANEL_VISIBLE, visible);
			},
		});

		await joplin.views.menus.create('heyWhisper.menu', 'Hey Whisper', [
			{ commandName: 'heyWhisper.toggleRecording', accelerator: TOGGLE_ACCELERATOR },
			{ commandName: 'heyWhisper.cancelRecording', accelerator: CANCEL_ACCELERATOR },
			{ commandName: 'heyWhisper.openThisWeek' },
			{ commandName: 'heyWhisper.useSelectedNotebook' },
			{ commandName: 'heyWhisper.togglePanel' },
		], MenuItemLocation.Tools);
		await joplin.views.toolbarButtons.create('heyWhisper.toolbarRecord', 'heyWhisper.toggleRecording', ToolbarButtonLocation.NoteToolbar);

		await setupPanel();
	},
});
