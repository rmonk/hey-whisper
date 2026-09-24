// Talks JSON lines to the Hey Whisper engine: either a `hey-whisper --serve`
// process it spawns (started on first use and kept alive so the speech model
// stays loaded), or an engine already running as `hey-whisper --serve-socket`,
// which is how a Flatpak Joplin reaches a Hey Whisper it can't start itself.

import { spawn } from 'child_process';
import { connect } from 'net';
import { createInterface } from 'readline';
import { Readable } from 'stream';

export interface SidecarEvent {
	event: string;
	[key: string]: any;
}

type Listener = (evt: SidecarEvent) => void;

// What to talk to: a command to spawn, or the socket of a running engine
export type SidecarTarget = { argv: string[] } | { socket: string };

interface Connection {
	write(line: string): void;
	close(): void;
}

const STDERR_TAIL_LINES = 20;
// Matches run_serve's wait for an in-flight transcription after "quit"
const QUIT_GRACE_MS = 120000;

// Split a command line into argv, honouring single and double quotes.
export function splitCommand(command: string): string[] {
	const args: string[] = [];
	let current = '';
	let quote: string | null = null;
	let inArg = false;
	for (const ch of command) {
		if (quote) {
			if (ch === quote) quote = null;
			else current += ch;
		} else if (ch === '"' || ch === '\'') {
			quote = ch;
			inArg = true;
		} else if (/\s/.test(ch)) {
			if (inArg) args.push(current);
			current = '';
			inArg = false;
		} else {
			current += ch;
			inArg = true;
		}
	}
	if (quote) throw new Error(`Unterminated quote in command: ${command}`);
	if (inArg) args.push(current);
	return args;
}

export class Sidecar {
	private conn: Connection | null = null;
	// Commands are written strictly in call order, even while the engine is
	// still being resolved/started (e.g. a quick hold-release sends start then stop).
	private sendQueue: Promise<void> = Promise.resolve();

	// getTarget resolves what to run or connect to; it may throw to report why none was found.
	public constructor(private getTarget: () => Promise<SidecarTarget>, private listener: Listener) {}

	public get running(): boolean {
		return this.conn !== null;
	}

	public send(cmd: Record<string, any>): Promise<void> {
		const task = this.sendQueue.then(async () => {
			const conn = await this.ensureStarted();
			if (!conn) return;
			conn.write(`${JSON.stringify(cmd)}\n`);
		});
		this.sendQueue = task.catch(() => undefined);
		return task;
	}

	public stop(): void {
		if (!this.conn) return;
		const conn = this.conn;
		this.conn = null;
		conn.close();
	}

	// Restart so a changed command, a new install or ~/.config/hey-whisper.conf takes effect.
	public restart(): void {
		this.stop();
	}

	private async ensureStarted(): Promise<Connection | null> {
		if (this.conn) return this.conn;

		let target: SidecarTarget;
		try {
			target = await this.getTarget();
		} catch (error) {
			this.listener({ event: 'error', message: error.message });
			return null;
		}
		if ('socket' in target) return this.connectSocket(target.socket);
		if (!target.argv.length) {
			this.listener({ event: 'error', message: 'The Hey Whisper command is empty.' });
			return null;
		}
		return this.spawnProcess(target.argv);
	}

	// Delivers each JSON event line; anything else goes to onOther.
	private readEvents(input: Readable, onOther: (line: string) => void) {
		const lines = createInterface({ input });
		// readline re-emits the input's errors, and would throw without a
		// listener; the caller already reports them from the input itself.
		lines.on('error', () => undefined);
		lines.on('line', line => {
			if (!line.trim()) return;
			try {
				this.listener(JSON.parse(line));
			} catch (error) {
				onOther(line);
			}
		});
	}

	private spawnProcess(argv: string[]): Connection {
		const child = spawn(argv[0], argv.slice(1), { stdio: ['pipe', 'pipe', 'pipe'] });
		const conn: Connection = {
			write: line => { child.stdin.write(line); },
			close: () => {
				child.stdin.end(`${JSON.stringify({ cmd: 'quit' })}\n`);
				// Let it finish an in-flight transcription, then make sure it's gone.
				setTimeout(() => { if (child.exitCode === null) child.kill(); }, QUIT_GRACE_MS).unref();
			},
		};
		this.conn = conn;
		const stderrTail: string[] = [];
		const pushStderr = (line: string) => {
			stderrTail.push(line);
			if (stderrTail.length > STDERR_TAIL_LINES) stderrTail.shift();
		};
		// Writing to a process that just died raises EPIPE here rather than throwing
		child.stdin.on('error', error => pushStderr(`[stdin] ${error.message}`));
		this.listener({ event: 'starting', command: argv.join(' ') });

		this.readEvents(child.stdout, line => pushStderr(`[stdout] ${line}`));
		createInterface({ input: child.stderr }).on('line', pushStderr);

		child.on('error', error => {
			// Typically ENOENT: the command isn't on Joplin's PATH
			if (this.conn === conn) this.conn = null;
			this.listener({ event: 'error', message: `Could not start "${argv[0]}": ${error.message}` });
		});
		// Forget the process as soon as it exits so the next send() starts a new one...
		let unexpected = false;
		child.on('exit', () => {
			unexpected = this.conn === conn;
			if (unexpected) this.conn = null;
		});
		// ...but report it on 'close', once its remaining stdout/stderr lines have been
		// delivered (e.g. argparse's "unrecognized arguments" or a final transcript).
		child.on('close', (code, signal) => {
			this.listener({
				event: 'exited',
				code,
				signal,
				unexpected,
				stderr: stderrTail.join('\n'),
			});
		});

		return conn;
	}

	// The engine keeps running when we disconnect, so the model stays loaded
	// for next time (or for another app using it).
	private connectSocket(path: string): Connection {
		const socket = connect(path);
		const conn: Connection = {
			// Buffered until the connection is up, so early commands keep their order
			write: line => { socket.write(line); },
			close: () => { socket.end(); },
		};
		this.conn = conn;
		this.listener({ event: 'starting', command: `Hey Whisper engine at ${path}` });

		let connected = false;
		socket.on('connect', () => { connected = true; });
		this.readEvents(socket, () => undefined);

		let failed = false;
		socket.on('error', error => {
			failed = true;
			if (this.conn === conn) this.conn = null;
			this.listener({
				event: 'error',
				message: connected
					? `Lost the connection to the Hey Whisper engine: ${error.message}`
					: `Could not connect to the Hey Whisper engine at ${path}: ${error.message}`,
			});
		});
		socket.on('close', () => {
			const unexpected = this.conn === conn;
			if (unexpected) this.conn = null;
			if (!failed) this.listener({ event: 'exited', code: null, signal: null, unexpected, socket: path, stderr: '' });
		});

		return conn;
	}
}
