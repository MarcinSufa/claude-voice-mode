#!/usr/bin/env python3
"""Shared config + flag-file + playback-PID helpers for the text-to-speech voice mode.

Imported by auto_speak_hook.py, voicemode.py and speak.py (all live in this dir, so a
plain `import voice_config` resolves when any of them is run by path). Keeping this here
avoids duplicating the flag-file format and config defaults in three places.

State files (all under ~/.claude/):
  .voice-mode-on    flag: "" (off) | "ALL" | "PENDING" | "<session_id>|<unix_ts>"
  .voice-mode.json  optional user config (see DEFAULTS)
  .voice-playback.pid  PID of the currently-playing player (so a new reply can stop it)
"""
import json
import os
import re
import signal
import sys
import time
from shutil import which

HOME = os.path.expanduser("~")
FLAG_FILE = os.path.join(HOME, ".claude", ".voice-mode-on")
CONFIG_FILE = os.path.join(HOME, ".claude", ".voice-mode.json")
PID_FILE = os.path.join(HOME, ".claude", ".voice-playback.pid")

DEFAULTS = {
    "voice": "en-US-AndrewNeural",   # voice for English replies / one-off default
    "voice_pl": "pl-PL-MarekNeural",  # voice auto-used when a reply looks Polish
    "max_chars": 0,                   # 0 = no cap (read the whole reply); >0 caps at a sentence boundary
    "rate": "+0%",
    "pitch": "+0Hz",
    "stale_hours": 6,                 # a claimed session this idle is reclaimable
}


def load_config() -> dict:
    """Return DEFAULTS overlaid with any keys present in .voice-mode.json (missing/bad file is fine)."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            user = json.load(fh)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return cfg


# --- flag file (which session, if any, is allowed to speak) ---------------------------

def read_flag() -> str:
    try:
        with open(FLAG_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def parse_claim(raw: str):
    """Parse the flag into (kind, session_id, ts).

    kind: "off" | "all" | "pending" | "claimed". ts is 0.0 for legacy claims with no timestamp.
    """
    if not raw:
        return ("off", "", 0.0)
    if raw == "ALL":
        return ("all", "", 0.0)
    if raw == "PENDING":
        return ("pending", "", 0.0)
    sid, _, ts_str = raw.partition("|")
    try:
        ts = float(ts_str) if ts_str else 0.0
    except ValueError:
        ts = 0.0
    return ("claimed", sid, ts)


def is_stale(ts: float, stale_hours: float) -> bool:
    """A claim with a heartbeat older than stale_hours is reclaimable. ts<=0 (legacy) is never stale."""
    if ts <= 0:
        return False
    return (time.time() - ts) > stale_hours * 3600


def write_claim(session_id: str) -> None:
    """Claim/refresh voice mode for this session with a fresh heartbeat timestamp."""
    try:
        os.makedirs(os.path.dirname(FLAG_FILE), exist_ok=True)
        with open(FLAG_FILE, "w", encoding="utf-8") as fh:
            fh.write(f"{session_id}|{time.time():.0f}")
    except OSError:
        pass


# --- playback PID (so a fresh reply can stop the previous one talking over it) ---------

def write_pid(pid: int) -> None:
    try:
        with open(PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(pid))
    except OSError:
        pass


def read_pid():
    try:
        with open(PID_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def clear_pid() -> None:
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def stop_playback() -> None:
    """Stop the player this skill last started. The PID file is cleared BEFORE the kill, so the
    player's owner (speak.py) sees the PID is no longer its own and treats the exit as "stopped"."""
    pid = read_pid()
    clear_pid()
    kill_pid(pid)


def kill_pid(pid) -> None:
    """Best-effort terminate. os.kill TerminateProcess's on Windows; PID reuse risk is acceptable here."""
    if not pid:
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except (OSError, ValueError, ProcessLookupError):
        pass


# --- audio players (speak.py tries them in this order) ---------------------------------

# Players that block until the clip ends: their PID is tracked so --replace / `voicemode.py stop`
# can cut them off. edge-tts always writes MP3 data, so WAV-only players (aplay) are not listed.
_BLOCKING_PLAYERS = (
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("mpv", ["--no-video", "--no-terminal"]),
    ("mpg123", ["-q"]),
    ("afplay", []),  # macOS
)


def audio_players():
    """Return the players available here, in try order: [(name, argv_before_path, blocks)].

    blocks=False means a hand-off to the desktop's default app (Windows startfile, xdg-open):
    it returns at once, so the file must outlive the call and playback can't be stopped.
    argv is None for os.startfile.
    """
    found = []
    for name, extra in _BLOCKING_PLAYERS:
        exe = which(name)
        if exe:
            found.append((name, [exe] + extra, True))
    if sys.platform == "win32":
        found.append(("startfile", None, False))
    elif sys.platform != "darwin" and which("xdg-open"):
        found.append(("xdg-open", [which("xdg-open")], False))
    return found


# --- language detection (pick a Polish voice for Polish replies) -----------------------

_PL_CHARS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_PL_WORDS = {
    "się", "nie", "jest", "czy", "jak", "dla", "tak", "ale", "że", "już",
    "tylko", "można", "oraz", "lub", "więc", "tym", "albo", "gdzie", "który",
    "ten", "jako", "przez", "bardzo", "wszystko", "dzień", "dobry",
}


def detect_lang(text: str) -> str:
    """Return 'pl' if the text looks Polish, else 'en'. Diacritics are the strong signal;
    a stopword ratio handles diacritic-free Polish."""
    if any(ch in _PL_CHARS for ch in text):
        return "pl"
    words = re.findall(r"[a-ząćęłńóśźż]+", text.lower())
    if words:
        hits = sum(1 for w in words if w in _PL_WORDS)
        if hits / len(words) > 0.06:
            return "pl"
    return "en"
