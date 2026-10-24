# claude-voice-mode

Hear Claude talk. A Claude Code plugin that turns text into speech with [edge-tts](https://github.com/rany2/edge-tts) Microsoft neural voices (free, no API key; the text is sent to Microsoft's Edge read-aloud service) — and an opt-in **auto-speak mode** that reads Claude's replies aloud as you work.

- 🗣️ **One-off TTS** — "read this out loud" / `/text-to-speech` synthesizes any text and plays it.
- 🔊 **Auto-speak mode** — a `Stop` hook reads every reply aloud, gated by a toggle (silent until you opt in).
- 🎯 **Session-scoped** — only the one window you turn it on in speaks; every other session stays silent.
- 🇵🇱 **Language auto-detect** — Polish-looking replies use a Polish voice; everything else uses English.
- 🤫 **Silent playback** — plays via `ffplay`, `mpv`, `mpg123` or `afplay` (no popup window); a new reply stops the previous one.
- 💸 **Free, not offline** — no API keys, but edge-tts sends the text to Microsoft's public endpoint (see [Privacy](#privacy)).

## Install

```
/plugin marketplace add MarcinSufa/claude-voice-mode
/plugin install voice-mode@claude-voice-mode
```

Then install the runtime dependency, edge-tts:

```
pipx install edge-tts          # or: uv tool install edge-tts
```

Either puts the `edge-tts` command on your `PATH`, which the plugin uses when it can't import the module. You can also `pip install edge-tts` inside a virtualenv whose `bin/` is on your `PATH`. On Debian/Ubuntu don't `pip install --user` into the system Python: PEP 668 blocks it. On Windows, `python -m pip install --user edge-tts` is fine.

**Requirements:**
- Python 3.10+ on your `PATH` as `python3` (or `python` / `py` on Windows). The hook tries `python3`, then `python`, then `py`, and stays silent if none exists.
- An audio player. Tried in order: `ffplay`, `mpv`, `mpg123`, `afplay` (built into macOS), then your desktop's default app (Windows, `xdg-open`). Linux: `sudo apt install ffmpeg` (or `mpv` / `mpg123`); Windows: `winget install Gyan.FFmpeg`. With no player, one-off TTS saves the mp3 and prints its path, and auto-speak does nothing.
- On Windows, Claude Code runs the hook through Git Bash, so Git for Windows must be installed.

## Usage

### One-off
Just ask: *"read this out loud"*, *"say this"*, *"make a voiceover of …"* — or run the helper directly:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/speak.py" --voice en-US-AndrewNeural --text "Hello there"
```

### Auto-speak mode (reads every reply)
The plugin ships the `Stop` hook, so no settings.json editing is needed. It stays silent until you arm it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" on       # arm: this one session only
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" on all   # every session (global)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" off      # stop everywhere
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" stop     # cut current playback, stay on
python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" status
```

Or just tell Claude *"voice mode on"* / *"voice mode off"*. When armed, the **next session to reply claims it** via its `session_id`, and only that session speaks. A claim that goes idle past `stale_hours` is auto-released.

## Configuration

Optional `~/.claude/.voice-mode.json` overrides the defaults:

```json
{
  "voice": "en-US-AndrewNeural",
  "voice_pl": "pl-PL-MarekNeural",
  "max_chars": 0,
  "rate": "+0%",
  "pitch": "+0Hz",
  "stale_hours": 6
}
```

- `max_chars`: `0` = read the whole reply (default). A positive value caps at a sentence boundary.
- Find more voices: `edge-tts --list-voices` (or `python3 -m edge_tts --list-voices`).

## How it works

The `Stop` hook does a fast gate check, then hands off to a **detached worker** that waits for the transcript to finish flushing before extracting the final reply (avoids reading a pre-tool preamble), strips markdown, drops code blocks, and synthesizes. Because it's detached, your session is never blocked. Shared logic lives in `voice_config.py`. Tests: `cd skills/text-to-speech && python3 test_voice.py` (no network, no audio; covers the pure functions, the exact hook command from `hooks/hooks.json`, and the playback/cleanup paths).

## Privacy

Speech is synthesized by the [edge-tts](https://github.com/rany2/edge-tts) library, which sends the **text being spoken to Microsoft's public Edge "Read Aloud" endpoint** over the network to generate the audio. In auto-speak mode that means your assistant's reply text leaves your machine; for one-off synthesis it's whatever text you asked to be read.

- No API key and no account required, but it **is** a network call to a third party (Microsoft).
- Voice mode is **off by default** and opt-in per session, so nothing is sent until you turn it on.
- Don't enable voice mode for content you don't want leaving your machine. For fully offline TTS you'd swap in a local engine (not included).

## Limitations

- Auto-speak uses one fixed voice (a hook can't prompt); change it in `.voice-mode.json`.
- Long replies = long audio — send a new message or run `voicemode.py stop` to cut a readout short.

## License

MIT © Marcin Sufa
