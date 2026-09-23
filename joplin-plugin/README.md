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
- A Hey Whisper release newer than 0.6.2 (the first with `hey-whisper --serve`), installed with pip or as the Flatpak.

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

- **Panel** (**Tools → Hey Whisper → Show/hide panel**): the record button, a VU meter, the engine in use, and the last saved entry. <kbd>Esc</kbd> cancels a recording while the panel has focus.
- **Keyboard shortcut**: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd> starts and stops a recording. You can rebind it under **Tools → Options → Keyboard Shortcuts**.
- **Note toolbar**: the 🎤 button does the same as the shortcut.
- **Open this week's voice notes** jumps to the current weekly note.

**Recording mode** (in Options):

| Mode | Panel button | Shortcut / toolbar |
|---|---|---|
| Hold (default) | Press and hold to talk, release to finish | Toggles |
| Toggle | Click to start, click again to finish | Toggles |
| Silence | Click to start; stops when you pause | Starts; stops when you pause (or press again) |

Joplin shortcuts don't report key release, so push-to-talk only works with the panel button.

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
