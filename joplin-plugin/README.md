# Hey Whisper for Joplin

A Joplin desktop plugin that dictates voice notes into weekly notes, using the same speech-to-text engine as the [Hey Whisper](../README.md) app (Vulkan `whisper.cpp`, `faster-whisper`, or NVIDIA Parakeet/Canary).

Pick a notebook, and every transcript is appended to a note for the current week:

```
Voice Notes/               ← the notebook you choose
└── 2026/
    └── 09 - September/
        └── 2026-09-07      ← weekly note, titled with the week's Monday
```

The note body uses the same format as the app's `spoken-notes-*.md` files:

```markdown
# 2026-09-09

- [2026-09-09 12:08 EDT] Met with team to review whisper transcription pipeline.
- [2026-09-09 14:15 EDT] Added push-to-talk hotkey support and VU level indicator.

# 2026-09-10

- [2026-09-10 09:30 EDT] Standup: Flatpak packaging completed with Vulkan support.
```

A week that spans two months is filed under the month of its Monday.

## How it works

Joplin plugins run in JavaScript, so the plugin starts `hey-whisper --serve` in the background. That process records from the microphone and transcribes, and the two talk to each other in JSON lines over stdin/stdout. The plugin writes the notes through the Joplin data API. The engine starts on first use and keeps running, so the model loads only once per Joplin session.

The model, backend, note prefix and silence settings all come from `~/.config/hey-whisper.conf`, the same file the app uses. Change them in the app's Settings dialog or in that file. Then restart the engine by changing the command setting, or restart Joplin.

## Requirements

- Joplin desktop 3.7 or newer. Mobile isn't supported, because the plugin needs to start a local process.
- Hey Whisper 0.7.0 or newer (the first release with `hey-whisper --serve`), installed with pip or as the Flatpak.

## Install

1. Build the plugin, or download `org.heywhisper.joplin.jpl` from a GitHub release:
   ```bash
   cd joplin-plugin
   npm install
   npm run dist        # → publish/org.heywhisper.joplin.jpl
   ```
2. In Joplin, go to **Tools → Options → Plugins → ⚙ → Install from file** and pick the `.jpl`.
3. The plugin finds Hey Whisper on its own. It checks, in order:
   1. `~/.local/bin/hey-whisper` (pip `--user` / pipx)
   2. `hey-whisper` on PATH
   3. the Hey Whisper Flatpak (`org.heywhisper.HeyWhisper`)

   If Joplin itself is a Flatpak, it runs these checks on the host through `flatpak-spawn --host`. Grant that once with:
   `flatpak override --user --talk-name=org.freedesktop.Flatpak net.cozic.joplin_desktop`

   To use a specific install, set **Tools → Options → Hey Whisper → Hey Whisper command**, e.g. `/path/to/venv/bin/hey-whisper --serve`. Hover over the engine name in the panel to see which command is in use.

4. Select the notebook to hold your voice notes in the sidebar, then run **Tools → Hey Whisper → Use selected notebook for voice notes**. The panel also has a **Use selected notebook** link.

## Use

Recording is controlled from the 🎤 button in the note toolbar (top right) or the keyboard:

| Action | Button / shortcut |
|---|---|
| Start / finish a voice note | 🎤, or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd> |
| Cancel the current recording | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Backspace</kbd> |
| Open this week's voice notes | **Tools → Hey Whisper → Open this week's voice notes** |

The shortcuts work anywhere in Joplin while its window is focused. They aren't system-wide. You can rebind them under **Tools → Options → Keyboard Shortcuts**, but the pop-up hints keep naming the defaults.

Short pop-up messages show what's happening:
- "Starting Hey Whisper…", on first use while the engine loads
- "🎙️ Recording…"
- "Transcribing…"
- "Saved to Voice Notes › 2026-09-07: …" with the start of the text
- a message when nothing was recorded or a recording was cancelled
- errors, which include the transcript if it couldn't be saved

**Optional panel** (**Tools → Hey Whisper → Show/hide panel**): a sidebar with a big record button, a level meter, the engine in use and the last saved entry. It's hidden by default. While it's showing, messages appear in the panel instead of as pop-ups. <kbd>Esc</kbd> cancels a recording while the panel has focus.

**Recording mode** (in Options):

| Mode | 🎤 button / shortcut | Panel button |
|---|---|---|
| Toggle (default) | Press to start, press again to finish | Same |
| Silence | Press to start; stops when you pause (or press again) | Same |
| Hold | Toggles | Press and hold to talk, release to finish |

Joplin's toolbar buttons and shortcuts don't report release, so push-to-talk (Hold) needs the panel.

If you're editing the weekly note while a transcript arrives, Joplin reloads the note with the new entry. Unsaved edits typed in the last moment before that can be lost, so it's safest to dictate while viewing a different note.

## Development

```bash
npm install
npm test            # jest: weekly layout, markdown insertion, sidecar protocol
npm run dist        # build publish/org.heywhisper.joplin.jpl
```

`src/weekly.ts:insertEntry` is a port of `storage.py:append_note`, and its tests use expected output generated from the Python code. If you change one, change the other.

To try the engine by hand:

```bash
hey-whisper --serve
{"cmd": "start", "mode": "toggle"}
{"cmd": "stop"}
```

The protocol is documented at the top of `src/hey_whisper/serve.py`.
