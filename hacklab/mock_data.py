"""Fixtures for the mock backend. Replaced by the box profile loader in P2.

The sketch below is a mock written for this project in the shape of the
CrunchLabs IR Turret stock sketch (MIT, Copyright (c) 2025 Crunchlabs LLC).
The real stock sketch lands in boxes/ir-turret/stock/ in P2.
"""

BOXES = [
    {"id": "ir-turret", "name": "IR Turret", "picture": "/static/boxes/ir-turret.png"},
    {"id": "laser-synth", "name": "Laser Synthesizer", "picture": "/static/boxes/laser-synth.png"},
]

BEHAVIOURS = {
    "ir-turret": [
        {
            "id": "shake-no",
            "title": "Shake its head no",
            "description": "Press OK and the turret shakes its head side to side.",
            "tweakables": [
                {"name": "shakes", "value": 3, "range": [1, 10], "step": 1},
                {"name": "yawMoveSpeed", "value": 90, "range": [10, 90], "step": 10},
            ],
        },
        {
            "id": "nod-yes",
            "title": "Nod yes",
            "description": "Press OK and the turret nods up and down.",
            "tweakables": [{"name": "nods", "value": 3, "range": [1, 10], "step": 1}],
        },
        {
            "id": "fire-all",
            "title": "Fire everything",
            "description": "Press the star key and the turret fires all its darts.",
            "tweakables": [],
        },
    ],
    "laser-synth": [
        {
            "id": "stock",
            "title": "How it came",
            "description": "The sound and laser show it came with.",
            "tweakables": [],
        }
    ],
}

CONCEPTS = {
    "servo": {
        "title": "How a servo moves",
        "explanation": (
            "A servo is a small motor that listens for a number. The pitch servo "
            "goes to the angle you give it, like 100. The yaw servo is different: "
            "90 means stop, and numbers above or below 90 mean spin one way or the "
            "other. That is why turning the head is a speed plus a time, not an angle."
        ),
    },
    "loop": {
        "title": "Doing something again and again",
        "explanation": (
            "A loop repeats a block of code. shakeHeadNo(3) runs the same left-right "
            "move three times. Change the 3 and it shakes more or fewer times."
        ),
    },
    "remote": {
        "title": "How the remote talks to the turret",
        "explanation": (
            "The remote blinks an invisible light in a pattern. Each button has its "
            "own pattern, and the turret reads the pattern to know which button you "
            "pressed. The code checks the button and picks what to do."
        ),
    },
}

STOCK_SKETCH = """\
/*
 * Mock of the IRTurret Control Code (Copyright (c) 2025 Crunchlabs LLC)
 * MIT License. Real stock sketch lands in boxes/ir-turret/stock/ in P2.
 */
#pragma region PINS AND PARAMS
int yawMoveSpeed = 90;   // speed around 90 = stop  ///{"range":[10,90],"step":10}
int pitchMin = 33;       // lowest the head can look ///{"min":33,"max":100}
int pitchMax = 150;      // highest the head can look ///{"min":100,"max":150}
#pragma endregion

void setup() { homeServos(); }

void loop() {
  if (IrReceiver.decode()) {
    switch (IrReceiver.decodedIRData.command) {
      case 0x1C: shakeHeadNo(3); break;  ///{"range":[1,10]}
      case 0x16: fireAll(); break;
    }
    IrReceiver.resume();
  }
}
"""

# Which curiosity prompts the mock genie offers, keyed by words in the ask.
PROMPT_HINTS = {
    "shake": ["servo", "loop"],
    "nod": ["servo", "loop"],
    "press": ["remote"],
    "fire": ["remote"],
}


def prompts_for(text: str) -> list[dict[str, str]]:
    ids: list[str] = []
    for word, concept_ids in PROMPT_HINTS.items():
        if word in text.lower():
            ids += [c for c in concept_ids if c not in ids]
    ids = (ids or ["remote"])[:3]
    return [{"id": c, "question": f"Want to know: {CONCEPTS[c]['title'].lower()}?"} for c in ids]
