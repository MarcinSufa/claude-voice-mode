---
name: text-to-speech
description: Use when the user wants spoken audio of text — "read this out loud", "say this", "make audio/voiceover", "TTS", narrate a summary, or hear a response as speech. Uses edge-tts (free offline Microsoft neural voices), English or Polish.
---

# Text to Speech (edge-tts)

## FIRST: which thing is the user asking for?
Two distinct features live in this skill — don't conflate them:
- **"voice mode on/off" / "respond with audio" / "speak your replies"** → they want the **auto-speak Stop hook**. Run `voicemode.py on` (see Auto-speak mode) **immediately**. Do NOT manually synthesize a one-off clip — that's the wrong feature and skips the toggle that actually makes replies spoken.
- **"read this out loud" / "say this" / "make a voiceover" of specific text** → one-off synthesis. Use the Workflow below (confirm voice, script prep, `speak.py`).

## Overview
Turn text into a spoken `.mp3` using `edge-tts` (Microsoft neural voices, free, no API key). A helper script does synth + auto-play in one command.

**Voice selection:** if the user named a voice, use it. Otherwise default to `en-US-AndrewNeural` (or a Polish voice when the text is Polish). Only ask which voice when it's genuinely ambiguous — don't silently pick a surprising one.

## Workflow
1. **Get the text.** If voicing a prior answer or doc, first rewrite it as a **spoken-word script** (see Script prep) — never feed raw markdown.
2. **Confirm the voice** with the user (English `en-US-AndrewNeural` vs Polish `pl-PL-MarekNeural`, or another). Skip only if they already specified one.
3. **Synthesize + play** with the helper:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\speak.py" --voice <VOICE> --file <script.txt>
   ```
   Inline text instead of a file: `--text "Hello there"`. Generate without playing: `--no-play`.

## Script prep (the non-obvious part)
Markdown reads terribly aloud. Before synthesizing, rewrite into clean prose:
- Strip headings, bullets, backticks, links, emoji.
- Spell out so the voice says it right: `AI` → `A.I.`, `10x` → `ten-x`, `API` → `A.P.I.`, `TTS` → `T.T.S.`, URLs → "dot co" etc.
- Short sentences. Write it the way a person would *say* it, not write it.
- Save to a UTF-8 `.txt` file in your temp dir, then point `--file` at it.

## Quick reference
| Need | Flag |
|------|------|
| Speed up / slow down | `--rate +10%` / `--rate -10%` |
| Higher / lower pitch | `--pitch +5Hz` / `--pitch -5Hz` |
| Pick output path | `--out c:\tmp\name.mp3` |
| Generate, don't play | `--no-play` |
| Stop prior playback first | `--replace` (one voice at a time) |
| Delete temp out/`--file` after | `--cleanup` |
| List every voice | `python -m edge_tts --list-voices` |

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
A `Stop` hook (shipped by this plugin via `hooks/hooks.json`, running `auto_speak_hook.py`) speaks replies aloud — gated by a toggle, silent until opted in. Markdown is stripped, then the **whole reply** is synthesized to a unique temp file and played with `--replace` so a new reply **stops** the previous one instead of talking over it. Silent playback via ffplay. (Default `max_chars: 0` = no cap, read the full answer; set a positive `max_chars` to truncate at a sentence boundary instead.)

**Auto language**: a Polish-looking reply is read with the Polish voice automatically; everything else uses the English voice. **Config** lives in `~/.claude/.voice-mode.json` (optional) — override `voice`, `voice_pl`, `max_chars`, `rate`, `pitch`, `stale_hours`. This is how you change the auto-speak voice without editing code (the hook can't ask each time).

**Session-scoped by default** (the hook is global, but only ONE session speaks): the toggle arms `PENDING`; the first session to reply claims it via its `session_id` + a heartbeat timestamp, and every other session stays silent. If the owning session goes idle past `stale_hours` (default 6), the claim is auto-reclaimed by the next session — a dead session never leaves voice mode stuck.

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\voicemode.py" on       # arm: one session only
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\voicemode.py" on all   # every session (global)
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\voicemode.py" off      # stop everywhere (also stops playback)
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\voicemode.py" stop     # stop current playback, stay on
python "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech\voicemode.py" status
```
When the user says "voice mode on/off", run that toggle (see the disambiguation at the top). The `Stop` hook is auto-registered when the plugin is installed; if it doesn't fire right after install, restart Claude Code or open `/hooks` once. The flag and config files need no reload at all.

Logic lives in shared `voice_config.py` (config, flag parsing, staleness, language detection, playback PID); `test_voice.py` covers the pure functions (`python test_voice.py`).

## Common mistakes
- **Treating "voice mode on" as a synthesis request** — it means "arm the auto-speak hook." Run `voicemode.py on` right away; don't hand-synthesize a clip. (See the disambiguation at the top.)
- **`edge-tts: command not found`** — the CLI usually isn't on PATH. Use the helper script, or `python -m edge_tts ...`. Never assume the bare `edge-tts` command exists.
- **Feeding raw markdown** — the voice reads "hash hash", "asterisk", backticks, and mangles `AI`/`10x`. Always do Script prep first.
- **Picking a surprising voice silently** — if the user named a voice, use it; otherwise use the configured default. Confirm only when genuinely ambiguous.
- **Empty/whitespace text** — the helper exits with a clear error; check the source actually has content.

## Install (if missing)
`python -m pip install --user edge-tts`  (requires internet at synth time — it streams from Microsoft's endpoint).
