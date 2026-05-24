#!/usr/bin/env python3
"""Synthesize text to speech with edge-tts and (optionally) play it.

Thin wrapper so the whole job is one command instead of write-file + edge-tts + open.
The edge-tts CLI is often NOT on PATH even when the package is installed, so we use
the Python API directly (robust across machines).

Examples:
    python speak.py --voice en-US-AndrewNeural --file script.txt
    python speak.py --voice pl-PL-MarekNeural  --text "Cześć, jak się masz?"
    python speak.py --voice en-US-AndrewNeural --file script.txt --rate -8% --no-play

--replace : stop any playback this skill started before playing (one voice at a time).
--cleanup : delete the output mp3 (and the --file, if it's a temp file) after playing.
The auto-speak hook passes both so rapid replies don't overlap or litter temp.
"""
import argparse
import asyncio
import os
import subprocess
import sys
import tempfile

try:
    import edge_tts
except ImportError:
    sys.exit("edge-tts not installed. Run:  python -m pip install --user edge-tts")

import voice_config as vc


def kill_previous_playback() -> None:
    """Terminate the ffplay this skill last started, if it's still going."""
    pid = vc.read_pid()
    if pid:
        vc.kill_pid(pid)
        vc.clear_pid()


def play(path: str, replace: bool = False) -> None:
    """Play the audio (best-effort, cross-platform).

    Prefers ffplay (silent, no popup window, auto-exits) since ffmpeg is usually present.
    When replace=True, stops the prior ffplay first and records this one's PID so the next
    --replace call can stop it. Falls back to the OS default player.
    """
    from shutil import which

    try:
        if which("ffplay"):
            if replace:
                kill_previous_playback()
            proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
            )
            if replace:
                vc.write_pid(proc.pid)
            proc.wait()
            if replace and vc.read_pid() == proc.pid:
                vc.clear_pid()  # only clear if a newer reply hasn't already replaced us
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["afplay", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as exc:  # playback is non-fatal; the file still exists
        print(f"(could not auto-play: {exc}) file is at: {path}", file=sys.stderr)


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


async def synth(text: str, voice: str, out: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out)


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
    asyncio.run(synth(text, args.voice, out, args.rate, args.pitch))

    size = os.path.getsize(out)
    print(f"Wrote {out} ({size:,} bytes) voice={args.voice} rate={args.rate} pitch={args.pitch}")
    if not args.no_play:
        play(out, replace=args.replace)
    if args.cleanup:
        cleanup_temp(out, args.file)


if __name__ == "__main__":
    main()
