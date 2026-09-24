// Works out how to start `hey-whisper --serve` when no command is configured:
//   1. ~/.local/bin/hey-whisper (pip --user / pipx)
//   2. hey-whisper anywhere on PATH
//   3. the Hey Whisper Flatpak
// When Joplin itself runs as a Flatpak, the checks and the final command go
// through `flatpak-spawn --host`, since the host's binaries aren't visible
// from inside Joplin's sandbox.

import { execFile } from 'child_process';
import { accessSync, constants, existsSync } from 'fs';
import { homedir } from 'os';
import { delimiter, join } from 'path';

export const FLATPAK_APP_ID = 'org.heywhisper.HeyWhisper';
const SERVE_ARGS = ['--serve'];
const HOST_PREFIX = ['flatpak-spawn', '--host'];
const JOPLIN_FLATPAK_ID = 'net.cozic.joplin_desktop';

export const HOST_ACCESS_HINT = 'Joplin is a Flatpak and is not allowed to run commands on the host, so it cannot find Hey Whisper. '
	+ `Run \`flatpak override --user --talk-name=org.freedesktop.Flatpak ${JOPLIN_FLATPAK_ID}\` and restart Joplin, `
	+ 'or set the command in Tools > Options > Hey Whisper.';

export interface ResolveDeps {
	home: string;
	path: string;
	sandboxed: boolean; // Joplin is running inside a Flatpak
	isExecutable(file: string): boolean;
	// Runs argv to completion; resolves true when it exits with status 0.
	succeeds(argv: string[]): Promise<boolean>;
}

export interface ResolvedCommand {
	argv: string[];
	source: 'local' | 'path' | 'flatpak';
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
	};
}

export async function resolveCommand(deps: ResolveDeps = defaultDeps()): Promise<ResolvedCommand | null> {
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
