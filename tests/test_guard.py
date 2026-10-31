"""Code-side guard on every AI helper answer (P7): fragments stay inside the skeleton's
rules and kid-facing text stays clean, whatever the model returned."""

from hacklab.genie import GenieResult
from hacklab.guard import check


def sketch(**kw) -> GenieResult:
    base = dict(kind="sketch", message_kid="Press 7 and watch it shake.", changed="Added a shake.")
    return GenieResult(**{**base, **kw})


def test_clean_sketch_has_no_problems():
    r = sketch(
        params='int shakes = 3; ///{"range":[1,10],"label":"How many shakes"}',
        cases="case cmd7: shakeNo(shakes); break;",
    )
    assert check(r) == []


def test_fragments_may_not_escape_the_skeleton():
    r = sketch(params="#include <EEPROM.h>\nint x;", functions="void f(){ pinMode(13, OUTPUT); }")
    problems = check(r)
    assert any("#include" in p for p in problems)
    assert any("pinMode(" in p for p in problems)


def test_fragments_may_not_block_the_loop_or_touch_hardware_setup():
    r = sketch(loop="while (1) { fire(); }", functions="void g(){ Servo s; s.attach(13); }")
    joined = " ".join(check(r))
    assert "while (1)" in joined and ".attach(" in joined


def test_kid_text_has_no_links_emoji_or_app_mechanics():
    r = sketch(message_kid="Great! Now press upload and see https://example.com 🚀")
    joined = " ".join(check(r))
    assert "link" in joined and "emoji" in joined and "upload" in joined


def test_kid_text_may_not_leak_the_instructions_or_run_long():
    r = GenieResult(kind="explain", message_kid="Rules you never break: " + "x" * 500)
    joined = " ".join(check(r))
    assert "instructions" in joined and "long" in joined


def test_explain_with_clean_text_is_fine():
    msg = "The AI helper only helps with the turret. Want it to nod instead?"
    r = GenieResult(kind="explain", message_kid=msg)
    assert check(r) == []
