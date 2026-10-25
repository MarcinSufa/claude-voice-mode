#!/usr/bin/env python3
"""Claude Code `Stop` hook: speak the assistant's last reply aloud — when voice mode is ON.

Wiring: auto-registered by the voice-mode plugin via hooks/hooks.json, which runs
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/text-to-speech/auto_speak_hook.py"
on the Stop event (falling back to `python`, then `py`, and exiting 0 silently if none exists).
To wire it by hand, copy the command from hooks/hooks.json into settings.json -> hooks.Stop.

Toggle:  python3 voicemode.py on | off | status | stop   (presence of the flag file = ON)

Design notes:
- A hook is not an LLM: it strips markdown / drops code blocks with plain rules, then
  caps at a sentence boundary. Good enough for listening, not hand-crafted.
- Voice + length come from ~/.claude/.voice-mode.json (see voice_config.DEFAULTS); a
  Polish-looking reply auto-switches to the Polish voice.
- Each reply is synthesized to a unique temp file and played with --replace, so a new
  reply stops the previous one instead of talking over it.
- Never blocks the session: synth+play is launched detached, and the hook always exits 0.
- If no audio player is installed, nothing is synthesized (so no text is sent to Microsoft).
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time

import voice_config as vc

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SPEAK_PY = os.path.join(SKILL_DIR, "speak.py")
STALE_AFTER_S = 15 * 60
AUTO_SPEAK_TEMP_RE = re.compile(r"claude_auto_speak_\d+\.(?:mp3|txt)\Z")

# Spoken-out substitutions so the voice doesn't mangle initialisms (English replies only).
SAY_AS = {
    r"\bAI\b": "A.I.", r"\bAPI\b": "A.P.I.", r"\bAPIs\b": "A.P.I.s",
    r"\bURL\b": "U.R.L.", r"\bTTS\b": "T.T.S.", r"\bMCP\b": "M.C.P.",
    r"\bRLS\b": "R.L.S.", r"\bCLI\b": "C.L.I.", r"\bUI\b": "U.I.",
    r"\bPR\b": "P.R.",
}


def clean_markdown(text: str, lang: str = "en") -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)      # fenced code blocks -> drop
    text = re.sub(r"`([^`]*)`", r"\1", text)                     # inline code -> keep word
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)            # images -> drop
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)         # links -> link text
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)    # headings
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)             # blockquotes
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)         # bullet markers
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)         # numbered list markers
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.M)       # table rows -> drop
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)                # emphasis markers
    if lang == "en":  # initialism expansion is English-specific; skip it for Polish
        for pat, rep in SAY_AS.items():
            text = re.sub(pat, rep, text)
    text = re.sub(r"\n{2,}", ". ", text)                          # paragraph breaks -> pause
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)                   # collapse repeated pauses
    return text


def cap(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:  # limit<=0 -> no cap, read the whole reply
        return text
    window = text[:limit]
    end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    return (window[: end + 1] if end > 120 else window).strip()


def last_assistant_text(transcript_path: str) -> str:
    """Return the text of the most recent assistant message that has any prose."""
    found = ""
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, str):
                    parts = [content]
                else:
                    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                joined = " ".join(p for p in parts if p).strip()
                if joined:
                    found = joined  # keep the latest non-empty assistant text
    except OSError:
        return ""
    return found


def session_gate(payload, cfg) -> bool:
    """Decide whether THIS session should speak, and refresh its heartbeat if so.

    "ALL" -> always; "PENDING" or a stale claim -> this session claims it; an active claim
    -> only the owning session. Each speaking turn rewrites the claim with a fresh timestamp
    so a session that goes idle past stale_hours releases voice mode to the next one.
    """
    kind, owner, ts = vc.parse_claim(vc.read_flag())
    if kind == "off":
        return False
    if kind == "all":
        return True
    session_id = payload.get("session_id", "")
    if not session_id:
        return False
    if kind == "pending" or (kind == "claimed" and vc.is_stale(ts, cfg["stale_hours"])):
        vc.write_claim(session_id)  # claim (or reclaim a stale session)
        return True
    if kind == "claimed" and owner == session_id:
        vc.write_claim(session_id)  # heartbeat: keep the claim fresh
        return True
    return False


def settled_assistant_text(path: str, tries: int = 20, interval: float = 0.12) -> str:
    """Wait out the transcript-flush race.

    The Stop hook can fire a beat before the final assistant message is flushed to the
    JSONL, so a naive read returns the previous text block (e.g. a pre-tool preamble).
    Poll until two consecutive reads agree on a non-empty value (≈0.24s when already
    settled, up to ~2.4s if the flush is slow), then use that.
    """
    prev, best = None, ""
    for _ in range(tries):
        cur = last_assistant_text(path)
        if cur:
            best = cur
            if cur == prev:
                return cur
        prev = cur
        time.sleep(interval)
    return best


def sweep_stale(tmp_dir: str, now: float, max_age: float) -> list:
    """Remove old regular auto-speak temp files directly inside tmp_dir."""
    removed = []
    try:
        entries = os.scandir(tmp_dir)
    except OSError:
        return removed
    try:
        with entries:
            for entry in entries:
                if not AUTO_SPEAK_TEMP_RE.fullmatch(entry.name):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or now - info.st_mtime <= max_age:
                        continue
                    path = entry.path
                    os.remove(path)
                    removed.append(path)
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def speak_reply(transcript_path: str) -> None:
    """Worker (runs detached): extract the settled final reply, clean it, synth + play."""
    players = vc.audio_players()
    if not players:
        return  # nothing could play it, so don't send the reply to Microsoft at all
    cfg = vc.load_config()
    raw = settled_assistant_text(transcript_path)
    lang = vc.detect_lang(raw)
    voice = cfg["voice_pl"] if lang == "pl" else cfg["voice"]
    spoken = cap(clean_markdown(raw, lang), cfg["max_chars"])
    if not spoken:
        return

    # Unique per-reply files so a fast follow-up reply can't overwrite text mid-read.
    stamp = time.time_ns()
    tmp = tempfile.gettempdir()
    sweep_stale(tmp, time.time(), STALE_AFTER_S)
    script_path = os.path.join(tmp, f"claude_auto_speak_{stamp}.txt")
    out_path = os.path.join(tmp, f"claude_auto_speak_{stamp}.mp3")
    rc = 1
    try:
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(spoken)
        rc = subprocess.run(
            [sys.executable, SPEAK_PY, "--voice", voice, "--file", script_path,
             "--out", out_path, "--rate", cfg["rate"], "--pitch", cfg["pitch"],
             "--replace", "--cleanup"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
    finally:
        # speak.py --cleanup removes both files after playback. It keeps the mp3 when nothing
        # played it, or when a desktop app (xdg-open / startfile) still has to open it; only that
        # last case needs the file, so drop it otherwise (e.g. edge-tts missing or synth failed).
        handed_off = rc == 0 and any(not blocks for _, _, blocks in players)
        for path in (script_path, None if handed_off else out_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def main() -> None:
    # Worker mode (re-exec'd detached by the hook): do the slow settle+synth off the session path.
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        speak_reply(sys.argv[2])
        return

    # Hook mode: fast gate only, then hand off to a detached worker and return immediately
    # (so the session isn't blocked and the worker can wait for the transcript to flush).
    if not os.path.exists(vc.FLAG_FILE):
        sys.exit(0)

    cfg = vc.load_config()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    if not session_gate(payload, cfg):
        sys.exit(0)

    transcript_path = payload.get("transcript_path", "")
    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    if sys.platform == "win32":
        detach = {"creationflags": subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)}
    else:
        detach = {"start_new_session": True}  # own session: survives the hook's process group
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--worker", transcript_path],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, **detach,
        )
    except Exception:
        pass  # never let playback failure surface as a hook error
    sys.exit(0)


if __name__ == "__main__":
    main()
