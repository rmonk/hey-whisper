import { mkdtempSync, rmSync } from 'fs';
import { Server, Socket, createServer } from 'net';
import { tmpdir } from 'os';
import { join } from 'path';
import { createInterface } from 'readline';
import { Sidecar, SidecarEvent, splitCommand } from './sidecar';

describe('splitCommand', () => {
	test.each([
		['hey-whisper --serve', ['hey-whisper', '--serve']],
		['  flatpak run --command=hey-whisper org.heywhisper.HeyWhisper --serve ', ['flatpak', 'run', '--command=hey-whisper', 'org.heywhisper.HeyWhisper', '--serve']],
		['"/opt/Hey Whisper/bin/hey-whisper" --serve', ['/opt/Hey Whisper/bin/hey-whisper', '--serve']],
		['hey-whisper --prefix \'[%H:%M]\' --serve', ['hey-whisper', '--prefix', '[%H:%M]', '--serve']],
		['hey-whisper --prefix "" --serve', ['hey-whisper', '--prefix', '', '--serve']],
		['', []],
	])('%j', (command, argv) => {
		expect(splitCommand(command)).toEqual(argv);
	});

	test('rejects unterminated quotes', () => {
		expect(() => splitCommand('hey-whisper "--serve')).toThrow(/Unterminated/);
	});
});

// A stand-in for `hey-whisper --serve` speaking the same JSON-lines protocol.
const FAKE_SIDECAR = `
const rl = require('readline').createInterface({ input: process.stdin });
const emit = obj => process.stdout.write(JSON.stringify(obj) + '\\n');
emit({ event: 'ready', backend: 'fake', model: 'tiny' });
console.error('some log line on stderr');
process.stdout.write('not json\\n');
rl.on('line', line => {
	const msg = JSON.parse(line);
	if (msg.cmd === 'start') emit({ event: 'recording', mode: msg.mode });
	if (msg.cmd === 'stop') emit({ event: 'transcript', text: 'hi', day: '2026-09-09', entry_line: '- hi' });
	if (msg.cmd === 'crash') process.exit(3);
	if (msg.cmd === 'quit') process.exit(0);
});
`;

function waitFor(events: SidecarEvent[], until: (e: SidecarEvent) => boolean): Promise<void> {
	return new Promise(resolve => {
		const check = setInterval(() => {
			if (events.some(until)) {
				clearInterval(check);
				resolve();
			}
		}, 10);
	});
}

describe('Sidecar', () => {
	const command = `"${process.execPath}" -e "${FAKE_SIDECAR.replace(/"/g, '\'').replace(/\n/g, ' ')}"`;

	test('round-trips commands and events', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ argv: splitCommand(command) }), e => events.push(e));

		await sidecar.send({ cmd: 'start', mode: 'toggle' });
		await sidecar.send({ cmd: 'stop' });
		await waitFor(events, e => e.event === 'transcript');

		expect(events.map(e => e.event)).toEqual(['starting', 'ready', 'recording', 'transcript']);
		expect(events[3].entry_line).toBe('- hi');

		sidecar.stop();
		await waitFor(events, e => e.event === 'exited');
		expect(events[events.length - 1]).toMatchObject({ event: 'exited', code: 0, unexpected: false });
	});

	test('reports an unexpected exit with the stderr tail and restarts on next send', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ argv: splitCommand(command) }), e => events.push(e));

		await sidecar.send({ cmd: 'crash' });
		await waitFor(events, e => e.event === 'exited');
		const exited = events.find(e => e.event === 'exited');
		expect(exited).toMatchObject({ code: 3, unexpected: true });
		expect(exited.stderr).toContain('some log line on stderr');
		expect(exited.stderr).toContain('[stdout] not json');
		expect(sidecar.running).toBe(false);

		await sidecar.send({ cmd: 'start', mode: 'silence' });
		await waitFor(events, e => e.event === 'recording');
		expect(events.filter(e => e.event === 'starting')).toHaveLength(2);
		sidecar.stop();
	});

	test('reports a missing executable', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ argv: ['definitely-not-hey-whisper', '--serve'] }), e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		await waitFor(events, e => e.event === 'error');
		expect(events.find(e => e.event === 'error').message).toMatch(/Could not start "definitely-not-hey-whisper"/);
		expect(sidecar.running).toBe(false);
	});

	test('reports why no command could be resolved', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => { throw new Error('Hey Whisper not found'); }, e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		expect(events).toEqual([{ event: 'error', message: 'Hey Whisper not found' }]);
		expect(sidecar.running).toBe(false);
	});

	test('writes commands in call order even while the command is still resolving', async () => {
		const events: SidecarEvent[] = [];
		let calls = 0;
		const sidecar = new Sidecar(async () => {
			// The first resolution is slower than any later one would be
			calls++;
			await new Promise(resolve => setTimeout(resolve, calls === 1 ? 200 : 0));
			return { argv: splitCommand(command) };
		}, e => events.push(e));

		// A quick hold-release: start and stop issued back to back
		void sidecar.send({ cmd: 'start', mode: 'toggle' });
		void sidecar.send({ cmd: 'stop' });
		await waitFor(events, e => e.event === 'transcript');

		expect(calls).toBe(1);
		expect(events.map(e => e.event)).toEqual(['starting', 'ready', 'recording', 'transcript']);
		sidecar.stop();
	});

	test('includes output written just before an immediate exit', async () => {
		// Like argparse rejecting an unknown --serve flag on an old install. The
		// noise overfills the pipe so the last line tends to be read late; the
		// report must still include it. Writes are synchronous (like Python's
		// stderr): process.stderr.write can drop queued output on process.exit.
		const script = 'const fs = require(\'fs\');'
			+ ' for (let i = 0; i < 20000; i++) fs.writeSync(2, `noise ${i}\\n`);'
			+ ' fs.writeSync(2, \'error: unrecognized arguments: --serve\\n\'); process.exit(2)';
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ argv: [process.execPath, '-e', script] }), e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		await waitFor(events, e => e.event === 'exited');
		expect(events.find(e => e.event === 'exited')).toMatchObject({
			code: 2,
			unexpected: true,
			stderr: expect.stringContaining('unrecognized arguments: --serve'),
		});
	});

	test('survives writing to a process that has already exited', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ argv: [process.execPath, '-e', 'process.stdin.destroy(); setTimeout(() => {}, 300)'] }), e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		await new Promise(resolve => setTimeout(resolve, 100));
		for (let i = 0; i < 5; i++) await sidecar.send({ cmd: 'status', pad: 'x'.repeat(100000) });
		await waitFor(events, e => e.event === 'exited');
		expect(events.find(e => e.event === 'exited').code).toBe(0);
	});
});

// A stand-in for `hey-whisper --serve-socket`
describe('Sidecar over a socket', () => {
	let dir: string;
	let path: string;
	let engine: Server;
	let received: string[];
	let clients: Socket[];

	beforeEach(async () => {
		dir = mkdtempSync(join(tmpdir(), 'hw-sock-'));
		path = join(dir, 'engine.sock');
		received = [];
		clients = [];
		engine = createServer(client => {
			clients.push(client);
			const emit = (obj: object) => client.write(`${JSON.stringify(obj)}\n`);
			emit({ event: 'ready', protocol: 1, backend: 'fake', model: 'tiny' });
			createInterface({ input: client }).on('line', line => {
				received.push(line);
				const msg = JSON.parse(line);
				if (msg.cmd === 'start') emit({ event: 'recording', mode: msg.mode });
				if (msg.cmd === 'stop') emit({ event: 'transcript', text: 'hi', day: '2026-09-24', entry_line: '- hi' });
			});
		});
		await new Promise<void>(resolve => engine.listen(path, resolve));
	});

	afterEach(async () => {
		for (const client of clients) client.destroy();
		await new Promise(resolve => engine.close(resolve));
		rmSync(dir, { recursive: true, force: true });
	});

	test('round-trips commands and leaves the engine running on stop', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ socket: path }), e => events.push(e));

		// Sent back to back while still connecting, like a quick hold-release
		void sidecar.send({ cmd: 'start', mode: 'toggle' });
		void sidecar.send({ cmd: 'stop' });
		await waitFor(events, e => e.event === 'transcript');
		expect(events.map(e => e.event)).toEqual(['starting', 'ready', 'recording', 'transcript']);
		expect(events[0].command).toContain(path);

		sidecar.stop();
		await waitFor(events, e => e.event === 'exited');
		expect(events[events.length - 1]).toMatchObject({ event: 'exited', unexpected: false, socket: path });
		// A spawned engine gets "quit"; a shared one must not
		expect(received.map(line => JSON.parse(line).cmd)).toEqual(['start', 'stop']);
		expect(engine.listening).toBe(true);
	});

	test('reports the engine going away and reconnects on next send', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ socket: path }), e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		await waitFor(events, e => e.event === 'ready');

		clients[0].end();
		await waitFor(events, e => e.event === 'exited');
		expect(events.find(e => e.event === 'exited')).toMatchObject({ unexpected: true, socket: path });
		expect(sidecar.running).toBe(false);

		await sidecar.send({ cmd: 'start', mode: 'silence' });
		await waitFor(events, e => e.event === 'recording');
		expect(events.filter(e => e.event === 'starting')).toHaveLength(2);
		sidecar.stop();
	});

	test('reports a socket nothing is listening on', async () => {
		const events: SidecarEvent[] = [];
		const sidecar = new Sidecar(async () => ({ socket: join(dir, 'missing.sock') }), e => events.push(e));
		await sidecar.send({ cmd: 'status' });
		await waitFor(events, e => e.event === 'error');
		expect(events.find(e => e.event === 'error').message).toMatch(/Could not connect to the Hey Whisper engine/);
		expect(events.some(e => e.event === 'exited')).toBe(false);
		expect(sidecar.running).toBe(false);
	});
});
