"""Genie: structured ask through a fake client, system prompt contents, prompts, refusal."""

import json
from pathlib import Path

import pytest

from hacklab.genie import FakeGenieClient, Genie, GenieRefused, GenieResult, prompts_for
from hacklab.profiles import load_boxes
from hacklab.skeleton import Fragments
from tests.conftest import SKELETON

GOLDEN = Path(__file__).parent / "golden"


def golden(name: str) -> list[dict]:
    return json.loads((GOLDEN / f"{name}.json").read_text())["responses"]


@pytest.mark.parametrize("name", [p.stem for p in sorted(GOLDEN.glob("*.json"))])
def test_every_golden_parses_as_a_genie_result(name):
    from hacklab.genie import ExplainResult

    for r in golden(name):
        if name.startswith("explain-"):  # P8: explanation goldens have their own shape
            res = ExplainResult(**r)
            assert res.title and res.story and res.steps
            continue
        res = GenieResult(**r)
        assert res.kind in {"sketch", "clarify", "explain"} and res.message_kid


@pytest.fixture
def box(boxes_dir: Path):
    return load_boxes(boxes_dir)["testbox"]


def test_system_prompt_has_persona_rules_hardware_helpers_and_skeleton(box):
    g = Genie(FakeGenieClient([]), "claude-sonnet-5-5", box, SKELETON)
    sp = g.system_prompt()
    for must in [
        "the AI helper",
        "11",
        "never ask",
        "no links",
        "One servo on pin 10",
        "wave(n)",
        "//@@CASES",
        "cmd1",
    ]:
        assert must.lower() in sp.lower(), must
    assert "http" not in sp


def test_ask_sends_cached_system_and_current_fragments(box):
    client = FakeGenieClient(golden("shake-head-on-7"))
    g = Genie(client, "claude-sonnet-5-5", box, SKELETON)
    res, usage = g.ask(
        "make it shake its head when I press 7", Fragments(cases="case 1: wave(1); break;")
    )
    assert res.kind == "sketch" and "cmd7" in res.cases
    assert usage.input_tokens > 0
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_format"] is GenieResult
    user = call["messages"][0]["content"]
    assert "case 1: wave(1); break;" in user and "make it shake its head" in user
    assert "budget_tokens" not in json.dumps(
        {k: v for k, v in call.items() if k != "output_format"}
    )


def test_retry_includes_the_compiler_error(box):
    client = FakeGenieClient(golden("compile-retry"))
    g = Genie(client, "claude-sonnet-5-5", box, SKELETON)
    g.ask("fire on 5", Fragments())
    g.ask("fire on 5", Fragments(), compile_error="error: expected ';' before 'break'")
    assert "expected ';'" in client.calls[1]["messages"][0]["content"]
    assert len(client.calls[1]["messages"]) == 1  # one call per turn, no history


def test_refusal_raises(box):
    client = FakeGenieClient([{"refusal": True}])
    with pytest.raises(GenieRefused):
        Genie(client, "claude-sonnet-5-5", box, SKELETON).ask("x", Fragments())


def test_prompts_filtered_to_box_concepts_max_three(box):
    res = GenieResult(kind="sketch", message_kid="ok", concepts=["servo", "nope", "loop", "servo"])
    assert prompts_for(res, box) == [
        {"id": "servo", "question": "Want to know how a servo moves?"},
        {"id": "loop", "question": "Want to know how Repeating works?"},
    ]
    many = GenieResult(
        kind="sketch", message_kid="ok", concepts=["servo", "loop", "servo", "loop", "servo"]
    )
    assert len(prompts_for(many, box)) <= 3
