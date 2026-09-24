import { FLATPAK_APP_ID, HOST_ACCESS_HINT, ResolveDeps, engineSocketPath, resolveCommand } from './resolveCommand';

const LOCAL = '/home/me/.local/bin/hey-whisper';
const SOCKET = '/home/me/.local/state/hey-whisper/engine.sock';
const FLATPAK_RUN = ['flatpak', 'run', '--command=hey-whisper', FLATPAK_APP_ID, '--serve'];

function deps(opts: { executables?: string[]; succeeding?: string[][]; sandboxed?: boolean; engineRunning?: boolean }): ResolveDeps & { calls: string[][] } {
	const calls: string[][] = [];
	return {
		calls,
		home: '/home/me',
		path: '/usr/local/bin:/usr/bin',
		sandboxed: !!opts.sandboxed,
		isExecutable: file => (opts.executables || []).includes(file),
		succeeds: async argv => {
			calls.push(argv);
			return (opts.succeeding || []).some(ok => ok.join(' ') === argv.join(' '));
		},
		listening: async path => !!opts.engineRunning && path === SOCKET,
	};
}

test('engineSocketPath', () => {
	expect(engineSocketPath('/home/me')).toBe(SOCKET);
});

describe('resolveCommand with a running engine', () => {
	test('prefers the socket over anything installed', async () => {
		const d = deps({ engineRunning: true, executables: [LOCAL] });
		expect(await resolveCommand(d)).toEqual({ socket: SOCKET, source: 'socket' });
	});

	test('uses the socket from a Flatpak Joplin without host access', async () => {
		const d = deps({ engineRunning: true, sandboxed: true });
		expect(await resolveCommand(d)).toEqual({ socket: SOCKET, source: 'socket' });
		expect(d.calls).toEqual([]);
	});
});

describe('resolveCommand on the host', () => {
	test('prefers ~/.local/bin', async () => {
		const d = deps({ executables: [LOCAL, '/usr/bin/hey-whisper'], succeeding: [['flatpak', 'info', FLATPAK_APP_ID]] });
		expect(await resolveCommand(d)).toEqual({ argv: [LOCAL, '--serve'], source: 'local' });
		expect(d.calls).toEqual([]);
	});

	test('falls back to PATH', async () => {
		const d = deps({ executables: ['/usr/bin/hey-whisper'] });
		expect(await resolveCommand(d)).toEqual({ argv: ['/usr/bin/hey-whisper', '--serve'], source: 'path' });
	});

	test('falls back to the Flatpak when not installed natively', async () => {
		const d = deps({ succeeding: [['flatpak', 'info', FLATPAK_APP_ID]] });
		expect(await resolveCommand(d)).toEqual({ argv: FLATPAK_RUN, source: 'flatpak' });
	});

	test('returns null when nothing is installed', async () => {
		expect(await resolveCommand(deps({}))).toBeNull();
	});
});

describe('resolveCommand when Joplin is a Flatpak', () => {
	const host = ['flatpak-spawn', '--host'];
	const hostOk = [...host, 'true'];

	test('checks ~/.local/bin on the host', async () => {
		const d = deps({ sandboxed: true, executables: [LOCAL], succeeding: [hostOk, [...host, 'test', '-x', LOCAL]] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, LOCAL, '--serve'], source: 'local' });
	});

	test('falls back to the host PATH', async () => {
		const d = deps({ sandboxed: true, succeeding: [hostOk, [...host, 'sh', '-c', 'command -v hey-whisper']] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, 'hey-whisper', '--serve'], source: 'path' });
	});

	test('falls back to the host Flatpak', async () => {
		const d = deps({ sandboxed: true, succeeding: [hostOk, [...host, 'flatpak', 'info', FLATPAK_APP_ID]] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, ...FLATPAK_RUN], source: 'flatpak' });
	});

	test('returns null when the host has nothing', async () => {
		expect(await resolveCommand(deps({ sandboxed: true, succeeding: [hostOk] }))).toBeNull();
	});

	test('explains the missing permission when flatpak-spawn --host is blocked', async () => {
		const d = deps({ sandboxed: true, succeeding: [[...host, 'flatpak', 'info', FLATPAK_APP_ID]] });
		await expect(resolveCommand(d)).rejects.toThrow(HOST_ACCESS_HINT);
		expect(d.calls).toEqual([hostOk]);
	});
});
