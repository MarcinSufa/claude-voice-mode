#!/usr/bin/env python3
"""Smoke tests for the pure logic in voice_config and auto_speak_hook.

Run:  python3 test_voice.py   (from the skill dir, so sibling imports resolve)
No network, no audio — the text/flag logic that's easy to get wrong, plus the hook command
from hooks/hooks.json and the playback/cleanup paths, run against fake players and a stub
edge_tts module in a temp HOME/TMPDIR (POSIX only; skipped on Windows).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import voice_config as vc
import auto_speak_hook as hook


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        check.failed += 1


check.failed = 0

# --- language detection ---
check("english stays english", vc.detect_lang("Let me fix the overlap bug for you.") == "en")
check("diacritics -> polish", vc.detect_lang("Cześć, jak się masz dzisiaj?") == "pl")
check("diacritic-free polish via stopwords", vc.detect_lang("To nie jest tak, ale czy dla nas to jest ok") == "pl")
check("english with 'this' not polish", vc.detect_lang("This is the thing that we should do now") == "en")

# --- claim parsing ---
check("empty -> off", vc.parse_claim("") == ("off", "", 0.0))
check("ALL", vc.parse_claim("ALL")[0] == "all")
check("PENDING", vc.parse_claim("PENDING")[0] == "pending")
kind, sid, ts = vc.parse_claim("abc123|1700000000")
check("claimed parses id+ts", kind == "claimed" and sid == "abc123" and ts == 1700000000.0)
check("legacy claim no ts", vc.parse_claim("abc123") == ("claimed", "abc123", 0.0))

# --- staleness ---
check("fresh claim not stale", not vc.is_stale(time.time(), 6))
check("old claim is stale", vc.is_stale(time.time() - 7 * 3600, 6))
check("legacy ts=0 never stale", not vc.is_stale(0.0, 6))

# --- markdown cleaning ---
cleaned = hook.clean_markdown("# Title\n\n- `code` and **bold** and a [link](http://x)", "en")
check("markdown stripped", "#" not in cleaned and "**" not in cleaned and "`" not in cleaned and "link" in cleaned)
check("english expands API", "A.P.I." in hook.clean_markdown("the API call", "en"))
check("polish skips API expansion", "A.P.I." not in hook.clean_markdown("the API call", "pl"))
# cap breaks on a sentence end only when it leaves >120 chars, else hard-truncates
check("cap breaks at sentence when far enough in", hook.cap("A" * 130 + ". " + "B" * 600, 200).endswith("."))
check("cap hard-truncates when no good boundary", len(hook.cap("x" * 600, 50)) == 50)

# --- config ---
cfg = vc.load_config()
check("config has voice", "voice" in cfg and "voice_pl" in cfg and "max_chars" in cfg)

# --- process-level checks (POSIX: they need bash and executable shell-script fakes) ---
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))
BASH = shutil.which("bash")


def make_exe(path, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)


def run(argv, home, path_dirs, stdin="", extra_env=None, tmpdir=None):
    env = {"HOME": home, "PATH": os.pathsep.join(path_dirs), "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
           "TMPDIR": tmpdir or home}
    env.update(extra_env or {})
    return subprocess.run(argv, input=stdin, env=env, capture_output=True, text=True, timeout=30)


def arm(home, content="PENDING"):
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    with open(os.path.join(home, ".claude", ".voice-mode-on"), "w", encoding="utf-8") as fh:
        fh.write(content)


def flag(home):
    with open(os.path.join(home, ".claude", ".voice-mode-on"), encoding="utf-8") as fh:
        return fh.read()


if os.name == "nt" or not BASH:
    print("SKIP process-level checks (need POSIX + bash)")
else:
    with open(os.path.join(PLUGIN_ROOT, "hooks", "hooks.json"), encoding="utf-8") as fh:
        stop_hook = json.load(fh)["hooks"]["Stop"][0]["hooks"][0]
    check("hooks.json Stop hook has timeout", stop_hook.get("timeout", 0) > 0)
    payload = json.dumps({"session_id": "s1", "transcript_path": "/nonexistent/t.jsonl"})

    with tempfile.TemporaryDirectory() as root:
        # Run the EXACT hooks.json command through bash, as Claude Code does, with a PATH that
        # holds only one interpreter name. A written claim proves the hook script really ran.
        for name in ("python3", "python"):
            only = os.path.join(root, "only-" + name)
            os.makedirs(only)
            os.symlink(sys.executable, os.path.join(only, name))
            home = os.path.join(root, "home-" + name)
            arm(home)
            r = run([BASH, "-c", stop_hook["command"]], home, [only], payload)
            check(f"hook command runs with only {name} on PATH",
                  r.returncode == 0 and r.stdout == "" and r.stderr == "" and flag(home).startswith("s1|"))

        empty = os.path.join(root, "empty-bin")
        os.makedirs(empty)
        home = os.path.join(root, "home-nopy")
        arm(home)
        r = run([BASH, "-c", stop_hook["command"]], home, [empty], payload)
        check("hook command with no python: exit 0, silent",
              r.returncode == 0 and r.stdout == "" and r.stderr == "" and flag(home) == "PENDING")

        home = os.path.join(root, "home-off")
        os.makedirs(home)
        r = run([BASH, "-c", stop_hook["command"]], home, [os.path.dirname(sys.executable)], payload)
        check("hook command with voice mode off: exit 0, silent",
              r.returncode == 0 and r.stdout == "" and r.stderr == "")

        home = os.path.join(root, "home-list")
        arm(home)
        r = run([sys.executable, os.path.join(SKILL_DIR, "auto_speak_hook.py")], home, [empty], "[1]")
        check("non-object JSON payload: exit 0, silent", r.returncode == 0 and r.stderr == "")

        # Stub edge_tts on PYTHONPATH: either broken (ImportError) or writing fake mp3 bytes.
        # It shadows any real install, so these checks never reach the network.
        stub_missing = os.path.join(root, "stub-missing")
        stub_ok = os.path.join(root, "stub-ok")
        os.makedirs(stub_missing)
        os.makedirs(stub_ok)
        with open(os.path.join(stub_missing, "edge_tts.py"), "w", encoding="utf-8") as fh:
            fh.write("raise ImportError('stub: edge-tts missing')\n")
        with open(os.path.join(stub_ok, "edge_tts.py"), "w", encoding="utf-8") as fh:
            fh.write("class Communicate:\n"
                     "    def __init__(self, text, voice, rate=None, pitch=None):\n"
                     "        pass\n"
                     "    async def save(self, out):\n"
                     "        open(out, 'wb').write(b'fake mp3')\n")

        # Fake players: ffplay fails (like no audio device), mpv succeeds and logs the file.
        players = os.path.join(root, "players")
        os.makedirs(players)
        played_log = os.path.join(root, "played.log")
        make_exe(os.path.join(players, "ffplay"), "exit 1")
        make_exe(os.path.join(players, "mpv"), f'for a; do last="$a"; done; echo "$last" >> "{played_log}"')

        speak = [sys.executable, os.path.join(SKILL_DIR, "speak.py"), "--voice", "en-US-AndrewNeural",
                 "--text", "hello", "--cleanup"]
        home = os.path.join(root, "home-speak")
        os.makedirs(home)
        out = os.path.join(home, "a.mp3")
        r = run(speak + ["--out", out], home, [players], extra_env={"PYTHONPATH": stub_ok})
        played = open(played_log).read().strip() if os.path.exists(played_log) else ""
        check("player chain falls through failing ffplay to mpv", r.returncode == 0 and played == out)
        check("--cleanup deletes the mp3 after it played", not os.path.exists(out))

        out = os.path.join(home, "b.mp3")
        r = run(speak + ["--out", out], home, [empty], extra_env={"PYTHONPATH": stub_ok})
        check("no player: rc 0, says where the file is", r.returncode == 0 and "file is at: " + out in r.stderr)
        check("no player: --cleanup keeps the only output", os.path.exists(out))

        # Worker with a player present but edge-tts missing: speak.py dies at synth time and the
        # worker must not leave its per-reply .txt (or a partial mp3) behind.
        home = os.path.join(root, "home-worker")
        tmpdir = os.path.join(root, "tmp-worker")
        os.makedirs(home)
        os.makedirs(tmpdir)
        transcript = os.path.join(root, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": "Done. All good."}}) + "\n")
        r = run([sys.executable, os.path.join(SKILL_DIR, "auto_speak_hook.py"), "--worker", transcript],
                home, [players], extra_env={"PYTHONPATH": stub_missing}, tmpdir=tmpdir)
        check("worker cleans temp files when edge-tts is missing",
              r.returncode == 0 and not os.listdir(tmpdir))

print()
print("ALL PASS" if check.failed == 0 else f"{check.failed} FAILED")
raise SystemExit(1 if check.failed else 0)
