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
		const sidecar = new Sidecar(async () => splitCommand(command), e => events.push(e));

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
		const sidecar = new Sidecar(async () => splitCommand(command), e => events.push(e));

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
		const sidecar = new Sidecar(async () => ['definitely-not-hey-whisper', '--serve'], e => events.push(e));
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
});
