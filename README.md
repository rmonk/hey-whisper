# Hey Whisper (🎙️)

A desktop voice-notes tool that listens on your default microphone, transcribes speech with **Vulkan GPU acceleration** (via `whisper.cpp`), [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), or **NVIDIA Parakeet/Canary** (via [`onnx-asr`](https://github.com/istupakov/onnx-asr)), and maintains weekly markdown logs organized by day.

---

## Features

- **Microphone Capture**: Uses `sounddevice` to stream audio directly from your default microphone via PipeWire or PulseAudio.
- **Hardware Acceleration via Vulkan**:
  - Full **Vulkan GPU acceleration** (works across NVIDIA, AMD, and Intel GPUs) via integrated `whisper.cpp` / `ggml-vulkan`.
  - Fallback to `faster-whisper` (CTranslate2) with quantized `int8` CPU / CUDA execution.
  - Automatically selects the fastest available backend (`auto`, `vulkan`, or `faster-whisper`).
- **NVIDIA Parakeet & Canary Support** (optional, `nemo` backend):
  - Runs NVIDIA's Parakeet (CTC/RNNT/TDT) and Canary (multilingual AED) models locally via the lightweight [`onnx-asr`](https://github.com/istupakov/onnx-asr) package — no PyTorch or the full NeMo toolkit required.
  - Never auto-selected; opt in explicitly by picking a Parakeet/Canary model and the `nemo` backend in Settings.
  - Install with: `pip install 'onnx-asr[cpu,hub]'` (or the `nemo` extra: `pip install '.[nemo]'`).
- **Three Trigger Modes**:
  - `hold` (*Default*): Push-to-talk. Press and hold a hotkey (default: <kbd>Space</kbd>) or mouse button to record; release to transcribe immediately.
  - `toggle`: Click or press hotkey to start recording, click or press again to finish.
  - `silence`: Voice Activity Detection (VAD). Begins capturing when you speak and automatically stops when you pause for a configurable duration (default: 1.5s).
- **Desktop GUI**:
  - **Left-Side Month Tree**: Notes grouped hierarchically by **Year $\rightarrow$ Month $\rightarrow$ Weekly File $\rightarrow$ Days**.
  - **Easy-to-Read & Edit Format**: Markdown editor with syntax coloring for headers, timestamps, and bullet points, alongside a rich rendered preview tab.
  - **Live VU Audio Meter**: Visual green-yellow-red bar confirms microphone input level in real time.
  - **Debounced Auto-Save**: In-place edits are saved automatically.
- **CLI Mode**: Run `hey-whisper --cli` for quick terminal note-taking or headless scripting.

---

## File Structure & Weekly Naming Rule

1. **Weekly Notes File**: Each file spans a calendar week (Monday through Sunday) and is named:
   ```
   spoken-notes-YYYY-MM-DD.md
   ```
   where `YYYY-MM-DD` is the **first day notes were recorded in that week**.
   - *Example*: If the first note of the week is recorded on Wednesday `2026-09-09`, the file is `spoken-notes-2026-09-09.md`.
   - Subsequent notes recorded on Thursday `2026-09-10` or Friday `2026-09-11` in the same week append under their respective day headers in `spoken-notes-2026-09-09.md`.

2. **Day Separation & Timestamps**:
   - Items are grouped under `# YYYY-MM-DD` headers.
   - Timestamps are formatted as `YYYY-MM-DD HH:MM TZ` (e.g. `2026-09-09 12:08 EDT`).

```markdown
# 2026-09-09

- [2026-09-09 12:08 EDT] Met with team to review whisper transcription pipeline.
- [2026-09-09 14:15 EDT] Added push-to-talk hotkey support and VU level indicator.

# 2026-09-10

- [2026-09-10 09:30 EDT] Standup: Flatpak packaging completed with Vulkan support.
```

---

## Configuration & Storage Priority

Hey Whisper determines where to save your notes using this priority order:
1. Command line option: `--dir /path/to/notes` (or `-d`)
2. Configuration file: `~/.config/hey-whisper.conf` (or fallback `~/.config/spoken-notes.conf`)
3. Current working directory (`.`) if neither is specified.

### Configuration File (`~/.config/hey-whisper.conf`)

```ini
[general]
notes_dir = ~/Documents/Notes
# Prefix template for new notes (supports standard strftime variables: %Y, %m, %d, %H, %M, %S, %Z)
note_prefix = [%Y-%m-%d %H:%M %Z]
# Theme: auto (follow OS light/dark mode), light, or dark
theme = auto
# Backend: auto (detects Vulkan GPU acceleration), vulkan, faster-whisper, or nemo
# (nemo runs NVIDIA Parakeet/Canary via onnx-asr; requires `pip install 'onnx-asr[cpu,hub]'`
# and is never chosen by "auto" — pick it explicitly along with a Parakeet/Canary model name)
backend = auto
# For backend=nemo, use a Parakeet/Canary preset instead, e.g.:
#   model = nemo-parakeet-tdt-0.6b-v3
#   model = nemo-canary-1b-v2
model = base.en
device = auto
compute_type = int8
vulkan_device = 0

[recording]
# Trigger mode: hold (default), toggle, or silence
mode = hold
# Default push-to-talk key in GUI
hotkey = Space
# Silence auto-stop threshold in seconds
silence_timeout = 1.5
# Silence RMS energy threshold
silence_threshold = 500
```

---

## Development & Virtualenv Testing

### 1. Set Up Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 2. Run Automated Tests

```bash
pytest -v
```

The test suite covers:
- Weekly file naming rule and date boundaries
- Markdown appending, day headers, and timestamp formatting
- Storage directory resolution priority (CLI > config file > CWD)
- Audio buffer and mock transcriber pipeline (both Vulkan and faster-whisper backends)
- GUI widgets (Month tree, Markdown editor, MainWindow)

### 3. Launch Locally

```bash
# Launch GUI
hey-whisper

# Launch CLI mode
hey-whisper --cli

# Specify notes folder, mode, and backend
hey-whisper -d ~/Notes -m hold --backend auto

# Use NVIDIA Parakeet/Canary via onnx-asr (requires: pip install 'onnx-asr[cpu,hub]')
hey-whisper --backend nemo --model nemo-parakeet-tdt-0.6b-v3
```

---

## Flatpak Packaging

A complete Freedesktop / Flatpak manifest is included in [`org.heywhisper.HeyWhisper.yaml`](org.heywhisper.HeyWhisper.yaml). It includes built-in Vulkan GPU acceleration and PipeWire audio capture.

### Build and Install with flatpak-builder

```bash
flatpak-builder --disable-rofiles-fuse --force-clean --user --install build-dir org.heywhisper.HeyWhisper.yaml
```

### Build Standalone Single-File Bundle (.flatpak)

```bash
flatpak build-export repo build-dir
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo repo hey-whisper.flatpak org.heywhisper.HeyWhisper
```

### Run Flatpak

```bash
flatpak run org.heywhisper.HeyWhisper
```

---

## Continuous Integration & Automated Releases (GitHub Actions)

A GitHub Actions workflow is set up at [`.github/workflows/flatpak.yml`](.github/workflows/flatpak.yml) to automatically:
1. **Run Unit Tests**: Executes the full test suite (`pytest`) in headless offscreen mode.
2. **Build Flatpak Application**: Uses `flatpak-builder` with cached builder state and Flathub runtimes.
3. **Generate Standalone Bundle**: Compiles `hey-whisper.flatpak` with embedded Flathub runtime repository metadata.
4. **Publish Workflow Artifact**: Uploads `hey-whisper.flatpak` as an artifact on the GitHub Actions run summary.
5. **Publish to GitHub Releases**:
   - On pushes to `main`: Updates the `latest` rolling continuous release with the newly built Flatpak bundle attached.
   - On version tags (`v*`): Creates a published release with release notes and the Flatpak bundle.

