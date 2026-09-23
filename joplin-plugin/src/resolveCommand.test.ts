import { FLATPAK_APP_ID, ResolveDeps, resolveCommand } from './resolveCommand';

const LOCAL = '/home/me/.local/bin/hey-whisper';
const FLATPAK_RUN = ['flatpak', 'run', '--command=hey-whisper', FLATPAK_APP_ID, '--serve'];

function deps(opts: { executables?: string[]; succeeding?: string[][]; sandboxed?: boolean }): ResolveDeps & { calls: string[][] } {
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
	};
}

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

	test('checks ~/.local/bin on the host', async () => {
		const d = deps({ sandboxed: true, executables: [LOCAL], succeeding: [[...host, 'test', '-x', LOCAL]] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, LOCAL, '--serve'], source: 'local' });
	});

	test('falls back to the host PATH', async () => {
		const d = deps({ sandboxed: true, succeeding: [[...host, 'sh', '-c', 'command -v hey-whisper']] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, 'hey-whisper', '--serve'], source: 'path' });
	});

	test('falls back to the host Flatpak', async () => {
		const d = deps({ sandboxed: true, succeeding: [[...host, 'flatpak', 'info', FLATPAK_APP_ID]] });
		expect(await resolveCommand(d)).toEqual({ argv: [...host, ...FLATPAK_RUN], source: 'flatpak' });
	});

	test('returns null when the host has nothing (or flatpak-spawn is not permitted)', async () => {
		expect(await resolveCommand(deps({ sandboxed: true }))).toBeNull();
	});
});
