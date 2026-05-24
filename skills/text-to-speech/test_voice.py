#!/usr/bin/env python3
"""Smoke tests for the pure logic in voice_config and auto_speak_hook.

Run:  python test_voice.py   (from the skill dir, so sibling imports resolve)
No network, no audio — just the text/flag logic that's easy to get wrong.
"""
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

print()
print("ALL PASS" if check.failed == 0 else f"{check.failed} FAILED")
raise SystemExit(1 if check.failed else 0)
