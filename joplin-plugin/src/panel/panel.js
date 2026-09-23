/* global webviewApi */
// Hey Whisper panel: record button, VU meter and status. All state lives in
// the plugin (src/index.ts); this script renders what it's sent.

(function() {
	const root = document.getElementById('hey-whisper-root');
	root.innerHTML = `
		<div class="hw-header">
			<span class="hw-title">🎙️ Hey Whisper</span>
			<span class="hw-engine"></span>
		</div>
		<button class="hw-record" type="button"></button>
		<div class="hw-meter"><div class="hw-meter-fill"></div></div>
		<div class="hw-message"></div>
		<div class="hw-last" hidden>
			<div class="hw-last-note"></div>
			<div class="hw-last-entry"></div>
		</div>
		<div class="hw-footer">
			<span class="hw-root"></span>
			<button class="hw-link hw-set-root" type="button">Use selected notebook</button>
			<button class="hw-link hw-open-week" type="button">Open this week</button>
		</div>
	`;

	const $ = selector => root.querySelector(selector);
	const recordButton = $('.hw-record');
	const meterFill = $('.hw-meter-fill');

	let state = null;
	let holding = false;
	// A click event follows every pointerup; it must not toggle after a hold.
	let suppressClick = false;

	const send = message => webviewApi.postMessage(message);

	const labels = {
		hold: { idle: 'Hold to talk', recording: 'Release to finish' },
		toggle: { idle: 'Start recording', recording: 'Finish recording' },
		silence: { idle: 'Start listening', recording: 'Finish now' },
	};

	function render() {
		if (!state) return;
		const modeLabels = labels[state.mode] || labels.toggle;
		const busy = state.status === 'starting' || state.status === 'transcribing';

		root.dataset.status = state.status;
		recordButton.textContent = state.status === 'recording' ? modeLabels.recording
			: state.status === 'starting' ? 'Starting engine…'
			: state.status === 'transcribing' ? 'Transcribing…'
			: modeLabels.idle;
		recordButton.disabled = busy && state.status !== 'transcribing';
		recordButton.classList.toggle('hw-recording', state.status === 'recording');

		$('.hw-engine').textContent = state.backend ? `${state.backend} · ${state.model}` : '';
		$('.hw-engine').title = state.command || '';
		$('.hw-root').textContent = state.rootTitle ? `Saving to: ${state.rootTitle}` : 'No notebook chosen';
		$('.hw-open-week').hidden = !state.rootTitle;

		const message = $('.hw-message');
		message.textContent = state.message;
		message.className = `hw-message ${state.messageKind ? `hw-${state.messageKind}` : ''}`;

		$('.hw-last').hidden = !state.lastEntry;
		$('.hw-last-note').textContent = state.lastNote ? `Last entry · ${state.lastNote}` : '';
		$('.hw-last-entry').textContent = state.lastEntry;

		if (state.status !== 'recording') meterFill.style.width = '0%';
	}

	function setLevel(rms) {
		// Same scale as the app's VU meter: RMS in int16 units, log-ish curve
		const pct = Math.min(100, Math.sqrt(rms / 8000) * 100);
		meterFill.style.width = `${pct}%`;
		meterFill.dataset.level = pct > 85 ? 'high' : pct > 60 ? 'mid' : 'low';
	}

	// Hold mode: push-to-talk on the button. Other modes: click toggles.
	recordButton.addEventListener('pointerdown', event => {
		if (!state || state.mode !== 'hold' || state.status === 'recording') return;
		holding = true;
		recordButton.setPointerCapture(event.pointerId);
		send({ type: 'holdStart' });
	});
	const endHold = () => {
		if (!holding) return;
		holding = false;
		suppressClick = true;
		send({ type: 'holdEnd' });
	};
	recordButton.addEventListener('pointerup', endHold);
	recordButton.addEventListener('pointercancel', endHold);
	recordButton.addEventListener('click', () => {
		if (suppressClick) {
			suppressClick = false;
			return;
		}
		if (!state) return;
		// In hold mode a click only stops a recording started from the keyboard shortcut
		if (state.mode !== 'hold' || state.status === 'recording') send({ type: 'toggle' });
	});
	document.addEventListener('keydown', event => {
		if (event.key === 'Escape' && state && state.status === 'recording') send({ type: 'cancel' });
	});

	$('.hw-set-root').addEventListener('click', () => send({ type: 'useSelectedNotebook' }));
	$('.hw-open-week').addEventListener('click', () => send({ type: 'openWeek' }));

	webviewApi.onMessage(event => {
		const message = event && event.message !== undefined ? event.message : event;
		if (!message) return;
		if (message.type === 'state') {
			state = message;
			render();
		} else if (message.type === 'level') {
			if (state && state.status === 'recording') setLevel(message.rms);
		}
	});

	send({ type: 'init' }).then(initial => {
		if (initial && !state) {
			state = initial;
			render();
		}
	});
})();
