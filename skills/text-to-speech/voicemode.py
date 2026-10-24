#!/usr/bin/env python3
"""Toggle auto-speak voice mode (used by the Stop hook auto_speak_hook.py).

Voice mode is SESSION-SCOPED by default so only one Claude session speaks:

    python3 voicemode.py on         # arm: the next session to reply claims it (one session only)
    python3 voicemode.py on all     # every session speaks (global)
    python3 voicemode.py off        # turn off everywhere (also stops current playback)
    python3 voicemode.py status     # report current state
    python3 voicemode.py stop       # stop the current playback now (voice mode stays on)

The flag file holds: "PENDING" (armed, unclaimed), "ALL" (global), or "<session_id>|<ts>"
(claimed, with a heartbeat). A claim idle past stale_hours is auto-reclaimed by the next
speaking session, so a dead session never leaves voice mode stuck.
"""
import sys

import voice_config as vc


def main() -> None:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    scope = (sys.argv[2] if len(sys.argv) > 2 else "").lower()

    if cmd == "on":
        import os
        os.makedirs(os.path.dirname(vc.FLAG_FILE), exist_ok=True)
        content = "ALL" if scope in ("all", "--all", "global") else "PENDING"
        with open(vc.FLAG_FILE, "w", encoding="utf-8") as fh:
            fh.write(content)
        if content == "ALL":
            print("voice mode: ON for ALL sessions")
        else:
            print("voice mode: ARMED — the next session to reply claims it, then ONLY that session speaks")

    elif cmd == "off":
        import os
        try:
            os.remove(vc.FLAG_FILE)
        except FileNotFoundError:
            pass
        vc.stop_playback()
        print("voice mode: OFF")

    elif cmd in ("stop", "shut-up", "quiet"):
        vc.stop_playback()
        print("playback stopped (voice mode still on)")

    elif cmd == "status":
        kind, owner, ts = vc.parse_claim(vc.read_flag())
        cfg = vc.load_config()
        if kind == "off":
            print("voice mode: OFF")
        elif kind == "all":
            print("voice mode: ON for all sessions")
        elif kind == "pending":
            print("voice mode: ARMED (waiting for a session to claim it)")
        elif vc.is_stale(ts, cfg["stale_hours"]):
            print(f"voice mode: ARMED — claim by session {owner[:8]}… is stale, next reply reclaims it")
        else:
            print(f"voice mode: ON for session {owner[:8]}… only")

    else:
        sys.exit("usage: voicemode.py on [all] | off | status | stop")


if __name__ == "__main__":
    main()
