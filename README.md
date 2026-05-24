# claude-voice-mode

Hear Claude talk. A Claude Code plugin that turns text into speech with free, offline [edge-tts](https://github.com/rany2/edge-tts) neural voices — and an opt-in **auto-speak mode** that reads Claude's replies aloud as you work.

- 🗣️ **One-off TTS** — "read this out loud" / `/text-to-speech` synthesizes any text and plays it.
- 🔊 **Auto-speak mode** — a `Stop` hook reads every reply aloud, gated by a toggle (silent until you opt in).
- 🎯 **Session-scoped** — only the one window you turn it on in speaks; every other session stays silent.
- 🇵🇱 **Language auto-detect** — Polish-looking replies use a Polish voice; everything else uses English.
- 🤫 **Silent playback** — plays via `ffplay` (no popup window); a new reply stops the previous one.
- 💸 **Free & offline-ish** — no API keys; edge-tts streams from Microsoft's public endpoint.

## Install

```
/plugin marketplace add MarcinSufa/claude-voice-mode
/plugin install voice-mode@claude-voice-mode
```

Then install the runtime dependency:

```
python -m pip install --user edge-tts
```

**Requirements:** Python 3.10+ on your `PATH` as `python`, and (recommended) `ffmpeg`/`ffplay` for silent playback. On Windows: `winget install Gyan.FFmpeg`. Without ffplay it falls back to your OS default player.

## Usage

### One-off
Just ask: *"read this out loud"*, *"say this"*, *"make a voiceover of …"* — or run the helper directly:

```
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/speak.py" --voice en-US-AndrewNeural --text "Hello there"
```

### Auto-speak mode (reads every reply)
The plugin ships the `Stop` hook, so no settings.json editing is needed. It stays silent until you arm it:

```
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" on       # arm: this one session only
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" on all   # every session (global)
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" off      # stop everywhere
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" stop     # cut current playback, stay on
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/voicemode.py" status
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
- Find more voices: `python -m edge_tts --list-voices`.

## How it works

The `Stop` hook does a fast gate check, then hands off to a **detached worker** that waits for the transcript to finish flushing before extracting the final reply (avoids reading a pre-tool preamble), strips markdown, drops code blocks, and synthesizes. Because it's detached, your session is never blocked. Shared logic lives in `voice_config.py`; `test_voice.py` covers the pure functions.

## Privacy

Speech is synthesized by the [edge-tts](https://github.com/rany2/edge-tts) library, which sends the **text being spoken to Microsoft's public Edge "Read Aloud" endpoint** over the network to generate the audio. In auto-speak mode that means your assistant's reply text leaves your machine; for one-off synthesis it's whatever text you asked to be read.

- No API key and no account required, but it **is** a network call to a third party (Microsoft).
- Voice mode is **off by default** and opt-in per session, so nothing is sent until you turn it on.
- Don't enable voice mode for content you don't want leaving your machine. For fully offline TTS you'd swap in a local engine (not included).

## Limitations

- Assumes `python` (3.10+) on `PATH`. On systems where Python is only `python3`, alias it or adjust the hook command.
- Auto-speak uses one fixed voice (a hook can't prompt); change it in `.voice-mode.json`.
- Long replies = long audio — send a new message or run `voicemode.py stop` to cut a readout short.

## License

MIT © Marcin Sufa
