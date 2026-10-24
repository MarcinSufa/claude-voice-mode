#!/usr/bin/env python3
"""Synthesize text to speech with edge-tts and (optionally) play it.

Thin wrapper so the whole job is one command instead of write-file + edge-tts + open.
The edge-tts CLI is often NOT on PATH even when the package is installed, so we use
the Python API when this interpreter can import it, and fall back to the `edge-tts`
command (what `pipx install` / `uv tool install` provide) when it can't.

Examples:
    python3 speak.py --voice en-US-AndrewNeural --file script.txt
    python3 speak.py --voice pl-PL-MarekNeural  --text "Cześć, jak się masz?"
    python3 speak.py --voice en-US-AndrewNeural --file script.txt --rate -8% --no-play

Playback tries ffplay, mpv, mpg123, afplay (macOS), then the desktop default app
(Windows startfile, Linux xdg-open). If none can play it, the mp3 is kept and its path printed.

--replace : stop any playback this skill started before playing (one voice at a time).
--cleanup : delete the output mp3 (and the --file, if it's a temp file) after it played.
            The mp3 is kept when nothing played it, or when it was handed to the desktop's
            default app (that app still needs the file).
The auto-speak hook passes both so rapid replies don't overlap or litter temp.
"""
import argparse
import asyncio
import os
import subprocess
import sys
import tempfile

from shutil import which

try:
    import edge_tts
except ImportError:
    edge_tts = None  # fall back to the `edge-tts` command, see synth()

import voice_config as vc

MISSING = ("edge-tts not installed. Install it with one of:  pipx install edge-tts  |  "
           "uv tool install edge-tts  |  a venv + pip install edge-tts  "
           "(Windows: python -m pip install --user edge-tts)")


def play(path: str, replace: bool = False) -> str:
    """Play the audio with the first player that works (best-effort, cross-platform).

    Returns "played" (a player finished it), "stopped" (cut off by --replace or
    `voicemode.py stop`), "launched" (handed to the desktop default app, which returns at
    once) or "none" (no player could play it; the path is printed instead).
    With replace=True, stops the prior player first and records this one's PID so the next
    --replace call can stop it.
    """
    players = vc.audio_players()
    for name, argv, blocks in players:
        try:
            if not blocks:
                if argv is None:
                    os.startfile(path)  # type: ignore[attr-defined]
                elif subprocess.run(argv + [path], stdin=subprocess.DEVNULL, check=False).returncode != 0:
                    continue
                return "launched"
            if replace:
                vc.stop_playback()
            proc = subprocess.Popen(argv + [path], stdin=subprocess.DEVNULL)
            if replace:
                vc.write_pid(proc.pid)
            rc = proc.wait()
            still_ours = vc.read_pid() == proc.pid
            if replace and still_ours:
                vc.clear_pid()  # only clear if a newer reply hasn't already replaced us
            if rc == 0:
                return "played"
            if rc < 0 or (replace and not still_ours):
                return "stopped"  # killed on purpose: don't fall through to the next player
        except Exception:
            continue  # this player failed to start or crashed; try the next one
    tried = ", ".join(p[0] for p in players) or "no player found on PATH"
    print(f"(could not auto-play; tried: {tried}) file is at: {path}", file=sys.stderr)
    return "none"


def cleanup_temp(*paths: str) -> None:
    """Delete each path that lives inside the system temp dir (never a user-supplied script)."""
    tmp = os.path.realpath(tempfile.gettempdir())
    for path in paths:
        if not path:
            continue
        try:
            if os.path.realpath(path).startswith(tmp) and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


async def synth_api(text: str, voice: str, out: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out)


def synth(text: str, voice: str, out: str, rate: str, pitch: str, text_file: str = "") -> None:
    """Write the speech to `out`, via the Python API or else the `edge-tts` command."""
    if edge_tts is not None:
        asyncio.run(synth_api(text, voice, out, rate, pitch))
        return
    cli = which("edge-tts")
    if not cli:
        sys.exit(MISSING)
    # "--opt=value" so values like "-10%" aren't parsed as flags; a file avoids argv size limits.
    src = f"--file={text_file}" if text_file else f"--text={text}"
    proc = subprocess.run(
        [cli, f"--voice={voice}", f"--rate={rate}", f"--pitch={pitch}", src, f"--write-media={out}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        sys.exit(f"edge-tts failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="edge-tts text-to-speech + play")
    ap.add_argument("--voice", required=True, help="e.g. en-US-AndrewNeural, pl-PL-MarekNeural")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="inline text to speak")
    src.add_argument("--file", help="path to a UTF-8 text file to speak")
    ap.add_argument("--out", help="output mp3 path (default: a temp file)")
    ap.add_argument("--rate", default="+0%", help="speed, e.g. -10%% or +10%% (default +0%%)")
    ap.add_argument("--pitch", default="+0Hz", help="pitch, e.g. -5Hz or +5Hz (default +0Hz)")
    ap.add_argument("--no-play", action="store_true", help="generate only, don't auto-play")
    ap.add_argument("--replace", action="store_true", help="stop prior skill playback before playing")
    ap.add_argument("--cleanup", action="store_true", help="delete temp out/--file after playing")
    args = ap.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = args.text
    if not text.strip():
        sys.exit("Nothing to speak: text is empty.")

    out = args.out or os.path.join(tempfile.gettempdir(), "speak.mp3")
    synth(text, args.voice, out, args.rate, args.pitch, text_file=args.file or "")

    size = os.path.getsize(out)
    print(f"Wrote {out} ({size:,} bytes) voice={args.voice} rate={args.rate} pitch={args.pitch}", flush=True)
    result = "not played (--no-play)"
    if not args.no_play:
        result = play(out, replace=args.replace)
    if args.cleanup:
        if result in ("played", "stopped"):
            cleanup_temp(out, args.file)
        else:
            cleanup_temp(args.file)  # never delete the only copy of audio nobody has heard
            why = {"none": "nothing could play it", "launched": "the default app still needs it"}
            print(f"Kept {out} ({why.get(result, result)})")


if __name__ == "__main__":
    main()
