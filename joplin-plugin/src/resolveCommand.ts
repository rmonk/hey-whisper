// Works out how to reach the Hey Whisper engine when no command is configured:
//   1. an engine already running with `hey-whisper --serve-socket`
//   2. ~/.local/bin/hey-whisper (pip --user / pipx)
//   3. hey-whisper anywhere on PATH
//   4. the Hey Whisper Flatpak
// 2-4 start `hey-whisper --serve`. When Joplin itself runs as a Flatpak, those
// checks and the final command go through `flatpak-spawn --host`, since the
// host's binaries aren't visible from inside Joplin's sandbox. The socket
// needs no such permission, so it's the only way that works out of the box.

import { execFile } from 'child_process';
import { accessSync, constants, existsSync } from 'fs';
import { connect } from 'net';
import { homedir } from 'os';
import { delimiter, join } from 'path';

export const FLATPAK_APP_ID = 'org.heywhisper.HeyWhisper';
const SERVE_ARGS = ['--serve'];
const HOST_PREFIX = ['flatpak-spawn', '--host'];
const JOPLIN_FLATPAK_ID = 'net.cozic.joplin_desktop';

const SOCKET_PROBE_MS = 2000;

export const HOST_ACCESS_HINT = 'Joplin is a Flatpak, so it cannot start Hey Whisper itself. '
	+ 'Open Hey Whisper (0.7.0 or newer) and turn on Settings > Keep the engine running for Joplin. '
	+ `Or let Joplin start it: run \`flatpak override --user --talk-name=org.freedesktop.Flatpak ${JOPLIN_FLATPAK_ID}\` and restart Joplin.`;

// Where `hey-whisper --serve-socket` listens by default. Built from the home
// directory rather than $XDG_STATE_HOME, which a Flatpak points elsewhere.
export function engineSocketPath(home: string): string {
	return join(home, '.local', 'state', 'hey-whisper', 'engine.sock');
}

export interface ResolveDeps {
	home: string;
	path: string;
	sandboxed: boolean; // Joplin is running inside a Flatpak
	isExecutable(file: string): boolean;
	// Runs argv to completion; resolves true when it exits with status 0.
	succeeds(argv: string[]): Promise<boolean>;
	// Resolves true when something accepts a connection on the Unix socket.
	listening(socketPath: string): Promise<boolean>;
}

export type ResolvedCommand =
	| { argv: string[]; source: 'local' | 'path' | 'flatpak' }
	| { socket: string; source: 'socket' };

function listening(socketPath: string): Promise<boolean> {
	return new Promise(resolve => {
		const socket = connect(socketPath);
		const done = (ok: boolean) => {
			socket.destroy();
			resolve(ok);
		};
		socket.setTimeout(SOCKET_PROBE_MS, () => done(false));
		socket.on('connect', () => done(true));
		socket.on('error', () => done(false));
	});
}

function isExecutable(file: string): boolean {
	try {
		accessSync(file, constants.X_OK);
		return true;
	} catch (error) {
		return false;
	}
}

function succeeds(argv: string[]): Promise<boolean> {
	return new Promise(resolve => {
		execFile(argv[0], argv.slice(1), { timeout: 10000 }, error => resolve(!error));
	});
}

export function defaultDeps(): ResolveDeps {
	return {
		home: homedir(),
		path: process.env.PATH || '',
		sandboxed: existsSync('/.flatpak-info'),
		isExecutable,
		succeeds,
		listening,
	};
}

export async function resolveCommand(deps: ResolveDeps = defaultDeps()): Promise<ResolvedCommand | null> {
	const socket = engineSocketPath(deps.home);
	if (await deps.listening(socket)) return { socket, source: 'socket' };

	const localBin = join(deps.home, '.local', 'bin', 'hey-whisper');

	if (deps.sandboxed) {
		// Without the org.freedesktop.Flatpak talk permission every host check
		// below would fail and look like "not installed", so say so up front.
		if (!(await deps.succeeds([...HOST_PREFIX, 'true']))) throw new Error(HOST_ACCESS_HINT);
		// Joplin's own PATH is the sandbox's, so ask the host shell instead.
		if (await deps.succeeds([...HOST_PREFIX, 'test', '-x', localBin])) {
			return { argv: [...HOST_PREFIX, localBin, ...SERVE_ARGS], source: 'local' };
		}
		if (await deps.succeeds([...HOST_PREFIX, 'sh', '-c', 'command -v hey-whisper'])) {
			return { argv: [...HOST_PREFIX, 'hey-whisper', ...SERVE_ARGS], source: 'path' };
		}
		if (await deps.succeeds([...HOST_PREFIX, 'flatpak', 'info', FLATPAK_APP_ID])) {
			return { argv: [...HOST_PREFIX, 'flatpak', 'run', '--command=hey-whisper', FLATPAK_APP_ID, ...SERVE_ARGS], source: 'flatpak' };
		}
		return null;
	}

	if (deps.isExecutable(localBin)) {
		return { argv: [localBin, ...SERVE_ARGS], source: 'local' };
	}
	for (const dir of deps.path.split(delimiter)) {
		if (!dir) continue;
		const candidate = join(dir, 'hey-whisper');
		if (deps.isExecutable(candidate)) return { argv: [candidate, ...SERVE_ARGS], source: 'path' };
	}
	if (await deps.succeeds(['flatpak', 'info', FLATPAK_APP_ID])) {
		return { argv: ['flatpak', 'run', '--command=hey-whisper', FLATPAK_APP_ID, ...SERVE_ARGS], source: 'flatpak' };
	}
	return null;
}
