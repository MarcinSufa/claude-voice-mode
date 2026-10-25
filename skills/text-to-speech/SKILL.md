---
name: text-to-speech
description: Use when the user wants spoken audio of text — "read this out loud", "say this", "make audio/voiceover", "TTS", narrate a summary, or hear a response as speech — or wants voice mode (auto-speak replies) on/off. Polish triggers - "przeczytaj na głos", "powiedz to", "nagraj lektora", "włącz/wyłącz voice mode". Uses edge-tts Microsoft neural voices, English or Polish - free, no API key; the text is sent to Microsoft's Edge read-aloud service.
---

# Text to Speech (edge-tts)

## FIRST: which thing is the user asking for?
Two distinct features live in this skill — don't conflate them:
- **"voice mode on/off" / "respond with audio" / "speak your replies"** → they want the **auto-speak Stop hook**. Run `voicemode.py on` (see Auto-speak mode) **immediately**. Do NOT manually synthesize a one-off clip — that's the wrong feature and skips the toggle that actually makes replies spoken.
- **"read this out loud" / "say this" / "make a voiceover" of specific text** → one-off synthesis. Use the Workflow below (pick voice, script prep, `speak.py`).

## Overview
Turn text into a spoken `.mp3` using `edge-tts` (Microsoft neural voices, free, no API key). The text is sent over the network to Microsoft's Edge read-aloud service, so it is not offline. A helper script does synth + auto-play in one command.

**Voice selection (one rule):** if the user named a voice, use it. Otherwise use the default for the text's language — `en-US-AndrewNeural` for English, `pl-PL-MarekNeural` for Polish (or `voice` / `voice_pl` from `~/.claude/.voice-mode.json` if set) — without asking. Ask only when you can't tell which language or voice they want.

## Workflow
1. **Get the text.** If voicing a prior answer or doc, first rewrite it as a **spoken-word script** (see Script prep) — never feed raw markdown.
2. **Pick the voice** per the rule above.
3. **Synthesize + play** with the helper:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/speak.py" --voice <VOICE> --file <script.txt>
   ```
   Inline text instead of a file: `--text "Hello there"`. Generate without playing: `--no-play`. On Windows use `python` (or `py`) instead of `python3`.
   If no player or audio device is available, it prints `file is at: <path>` and keeps the mp3; tell the user where it is.

## Script prep (the non-obvious part)
Markdown reads terribly aloud. Before synthesizing, rewrite into clean prose:
- Strip headings, bullets, backticks, links, emoji.
- Spell out so the voice says it right: `AI` → `A.I.`, `10x` → `ten-x`, `API` → `A.P.I.`, `TTS` → `T.T.S.`, URLs → "dot co" etc.
- Short sentences. Write it the way a person would *say* it, not write it.
- Save to a UTF-8 `.txt` file in the OS temp dir (`/tmp` on Linux/macOS, `%TEMP%` on Windows), then point `--file` at it.

## Quick reference
| Need | Flag |
|------|------|
| Speed up / slow down | `--rate +10%` / `--rate -10%` |
| Higher / lower pitch | `--pitch +5Hz` / `--pitch -5Hz` |
| Pick output path | `--out /tmp/name.mp3` (default: `speak.mp3` in the OS temp dir) |
| Generate, don't play | `--no-play` |
| Stop prior playback first | `--replace` (one voice at a time) |
| Delete temp out/`--file` after it played | `--cleanup` (keeps the mp3 if nothing played it) |
| List every voice | `edge-tts --list-voices` (or `python3 -m edge_tts --list-voices`) |

### Common voices
| Voice | Language / style |
|-------|------------------|
| `en-US-AndrewNeural` | English (US), conversational male |
| `en-US-BrianNeural` | English (US), warm male |
| `en-US-AvaNeural` | English (US), natural female |
| `en-GB-RyanNeural` | English (UK) male |
| `pl-PL-MarekNeural` | Polish male |
| `pl-PL-ZofiaNeural` | Polish female |

## Auto-speak mode (Stop hook)
A `Stop` hook (shipped by this plugin via `hooks/hooks.json`, running `auto_speak_hook.py`) speaks replies aloud — gated by a toggle, silent until opted in. Markdown is stripped, then the **whole reply** is synthesized to a unique temp file and played with `--replace` so a new reply **stops** the previous one instead of talking over it. Plays in the background with the first of ffplay, mpv, mpg123, afplay (macOS) that is installed, else the desktop's default app (Windows, `xdg-open`). If no player is installed, the hook does nothing (no text is sent). (Default `max_chars: 0` = no cap, read the full answer; set a positive `max_chars` to truncate at a sentence boundary instead.)
Auto-speak temp files left behind by desktop-app playback are swept on the next reply when they are older than 15 minutes.

**Auto language**: a Polish-looking reply is read with the Polish voice automatically; everything else uses the English voice. **Config** lives in `~/.claude/.voice-mode.json` (optional) — override `voice`, `voice_pl`, `max_chars`, `rate`, `pitch`, `stale_hours`. This is how you change the auto-speak voice without editing code (the hook can't ask each time).

**Session-scoped by default** (the hook is global, but only ONE session speaks): the toggle arms `PENDING`; the first session to reply claims it via its `session_id` + a heartbeat timestamp, and every other session stays silent. If the owning session goes idle past `stale_hours` (default 6), the claim is auto-reclaimed by the next session — a dead session never leaves voice mode stuck.

```bash
python3 "${CLAUDE_SKILL_DIR}/voicemode.py" on       # arm: one session only
python3 "${CLAUDE_SKILL_DIR}/voicemode.py" on all   # every session (global)
python3 "${CLAUDE_SKILL_DIR}/voicemode.py" off      # stop everywhere (also stops playback)
python3 "${CLAUDE_SKILL_DIR}/voicemode.py" stop     # stop current playback, stay on
python3 "${CLAUDE_SKILL_DIR}/voicemode.py" status
```
When the user says "voice mode on/off", run that toggle (see the disambiguation at the top). The `Stop` hook is auto-registered when the plugin is installed; if it doesn't fire right after install, restart Claude Code or open `/hooks` once. The flag and config files need no reload at all.

The hook command (in `hooks/hooks.json`) tries `python3`, then `python`, then `py`, and exits silently if none exists, so it never errors or blocks when voice mode is off or Python is missing.

Logic lives in shared `voice_config.py` (config, flag parsing, staleness, language detection, audio players, playback PID); `test_voice.py` covers the pure functions plus the hook command and playback/cleanup paths (`python3 test_voice.py` from this dir).

## Common mistakes
- **Treating "voice mode on" as a synthesis request** — it means "arm the auto-speak hook." Run `voicemode.py on` right away; don't hand-synthesize a clip. (See the disambiguation at the top.)
- **`edge-tts: command not found` / `No module named edge_tts`** — a pip/venv install gives the module but often no CLI on PATH; `pipx`/`uv tool` give the CLI but no importable module. The helper handles both, so always use it instead of calling `edge-tts` directly.
- **Feeding raw markdown** — the voice reads "hash hash", "asterisk", backticks, and mangles `AI`/`10x`. Always do Script prep first.
- **Asking about the voice when the rule already answers it** — named voice, else the language default (see Voice selection). Ask only when the language or voice is unclear.
- **Empty/whitespace text** — the helper exits with a clear error; check the source actually has content.

## Install (if missing)
`pipx install edge-tts` or `uv tool install edge-tts` (puts the `edge-tts` command on PATH; the helper falls back to it). Or `pip install edge-tts` inside a virtualenv whose `bin/` is on PATH. Don't `pip install --user` into the system Python on Debian/Ubuntu (PEP 668 blocks it). Windows: `python -m pip install --user edge-tts`. Needs internet at synth time: it streams from Microsoft's endpoint.

A player: Linux `sudo apt install ffmpeg` (ffplay) or `mpv` / `mpg123`; macOS has `afplay` built in; Windows `winget install Gyan.FFmpeg`.
