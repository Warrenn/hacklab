"""Code-side guard on every AI helper answer (STRATEGY P7). The persona asks for
these rules; this enforces them whatever the model returned. `check()` returns
plain-English problems; the runner feeds them back to the model (sketch) or
declines (explain/clarify)."""

from __future__ import annotations

import re

from hacklab.genie import GenieResult

# Fragments live inside a fixed skeleton: no new includes, pins, hardware setup,
# persistent storage or loops that would starve the box's own loop().
FORBIDDEN_CODE = (
    "#include",
    "pinMode(",
    ".attach(",
    "Serial.begin(",
    "asm",
    "goto",
    "EEPROM",
    "while (1)",
    "while(1)",
    "while (true)",
    "while(true)",
    "for (;;)",
    "for(;;)",
)
URL = re.compile(r"https?://|www\.", re.I)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
# The app sends the code to the box by itself; the kid never uploads or flashes.
APP_MECHANICS = re.compile(r"\b(upload|flash|flashing|slider|sliders)\b", re.I)
# Phrases that only occur in the system prompt.
LEAK = ("Rules you never break", "insertion point", "//@@", "skeleton")
MAX_KID_TEXT = 400


def check_text(fields: dict[str, str], max_len: int = MAX_KID_TEXT) -> list[str]:
    """Kid-facing text rules, for any named fields (explanations use longer limits)."""
    problems: list[str] = []
    for name, text in fields.items():
        if URL.search(text):
            problems.append(f"{name} contains a link")
        if EMOJI.search(text):
            problems.append(f"{name} contains an emoji")
        if any(k.lower() in text.lower() for k in LEAK):
            problems.append(f"{name} repeats the instructions")
        if len(text) > max_len:
            problems.append(f"{name} is too long ({len(text)} chars, max {max_len})")
    return problems


def check(result: GenieResult) -> list[str]:
    problems: list[str] = []
    code = "\n".join((result.params, result.cases, result.loop, result.functions))
    for token in FORBIDDEN_CODE:
        if token in code:
            problems.append(f"code uses {token}, which is not allowed in a fragment")
    if URL.search(code):
        problems.append("code contains a link")
    for name, text in (("message_kid", result.message_kid), ("changed", result.changed)):
        if URL.search(text):
            problems.append(f"{name} contains a link")
        if EMOJI.search(text):
            problems.append(f"{name} contains an emoji")
        if m := APP_MECHANICS.search(text):
            problems.append(f"{name} mentions '{m.group(0)}'; the app does that by itself")
        if any(k.lower() in text.lower() for k in LEAK):
            problems.append(f"{name} repeats the instructions")
        if len(text) > MAX_KID_TEXT:
            problems.append(f"{name} is too long ({len(text)} chars, max {MAX_KID_TEXT})")
    return problems
