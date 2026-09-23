// Spawns `hey-whisper --serve` and exchanges JSON lines with it. The process
// is started on first use and kept alive so the speech model stays loaded.

import { ChildProcess, spawn } from 'child_process';
import { createInterface } from 'readline';

export interface SidecarEvent {
	event: string;
	[key: string]: any;
}

type Listener = (evt: SidecarEvent) => void;

const STDERR_TAIL_LINES = 20;

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
	private child: ChildProcess | null = null;
	private stderrTail: string[] = [];

	// getArgv resolves the command to run; it may throw to report why none was found.
	public constructor(private getArgv: () => Promise<string[]>, private listener: Listener) {}

	public get running(): boolean {
		return this.child !== null;
	}

	public async send(cmd: Record<string, any>): Promise<void> {
		const child = await this.ensureStarted();
		if (!child) return;
		child.stdin.write(`${JSON.stringify(cmd)}\n`);
	}

	public stop(): void {
		if (!this.child) return;
		const child = this.child;
		this.child = null;
		child.stdin.end(`${JSON.stringify({ cmd: 'quit' })}\n`);
		// Give it a moment to finish an in-flight transcription, then make sure it's gone.
		setTimeout(() => { if (child.exitCode === null) child.kill(); }, 5000).unref();
	}

	// Restart so a changed command, a new install or ~/.config/hey-whisper.conf takes effect.
	public restart(): void {
		this.stop();
	}

	private async ensureStarted(): Promise<ChildProcess | null> {
		if (this.child) return this.child;

		let argv: string[];
		try {
			argv = await this.getArgv();
		} catch (error) {
			this.listener({ event: 'error', message: error.message });
			return null;
		}
		// Another send() may have started the process while we were resolving
		if (this.child) return this.child;
		if (!argv.length) {
			this.listener({ event: 'error', message: 'The Hey Whisper command is empty.' });
			return null;
		}

		this.stderrTail = [];
		const child = spawn(argv[0], argv.slice(1), { stdio: ['pipe', 'pipe', 'pipe'] });
		this.child = child;
		this.listener({ event: 'starting', command: argv.join(' ') });

		createInterface({ input: child.stdout }).on('line', line => {
			if (!line.trim()) return;
			try {
				this.listener(JSON.parse(line));
			} catch (error) {
				this.pushStderr(`[stdout] ${line}`);
			}
		});
		createInterface({ input: child.stderr }).on('line', line => this.pushStderr(line));

		child.on('error', error => {
			// Typically ENOENT: the command isn't on Joplin's PATH
			if (this.child === child) this.child = null;
			this.listener({ event: 'error', message: `Could not start "${argv[0]}": ${error.message}` });
		});
		child.on('exit', (code, signal) => {
			const wasCurrent = this.child === child;
			if (wasCurrent) this.child = null;
			this.listener({
				event: 'exited',
				code,
				signal,
				unexpected: wasCurrent,
				stderr: this.stderrTail.join('\n'),
			});
		});

		return child;
	}

	private pushStderr(line: string) {
		this.stderrTail.push(line);
		if (this.stderrTail.length > STDERR_TAIL_LINES) this.stderrTail.shift();
	}
}
