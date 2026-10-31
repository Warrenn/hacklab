"""Shared fixtures: a tiny on-disk box profile for profile/API tests."""

from pathlib import Path

import pytest

SKELETON = """\
#include <Servo.h>
Servo s;
//@@PARAMS
void wave(int n) {
  for (int i = 0; i < n; i++) { s.write(60); delay(200); s.write(120); delay(200); }
}
//@@FUNCTIONS
void setup() { s.attach(10); }
void loop() {
    //@@LOOP
    int key = 0;
    switch (key) {
        case 1: wave(1); break;
        //@@CASES
    }
}
"""

STOCK_MAIN = (
    '#include "config.h"\nint speed = 5; // how fast -- ///{"range":[1,10]}\n'
    "void setup(){} void loop(){}\n"
)

SKETCH = """\
#include <Servo.h>
Servo s;
int shakes = 3; // how many -- ///{"range":[1,10],"step":1}
int speed = 90; ///{"min":10,"max":90}
bool fast = false; ///{"options":["true","false"]}
void setup() { s.attach(10); }
void loop() { for (int i = 0; i < shakes; i++) { s.write(speed); delay(200); } }
"""


def write_box(
    root: Path,
    box_id: str = "testbox",
    *,
    stock_location: str = "repo",
    copy: bool = True,
    fqbn: str = "arduino:avr:nano",
) -> Path:
    b = root / box_id
    (b / "behaviours" / "shake").mkdir(parents=True)
    (b / "templates" / "wave").mkdir(parents=True)
    (b / "stock" / "stock").mkdir(parents=True)
    (b / "genie").mkdir()
    (b / "genie" / "skeleton.ino").write_text(SKELETON)
    (b / "profile.toml").write_text(
        f'id = "{box_id}"\nname = "Test Box"\npicture = "/static/boxes/{box_id}.svg"\n'
        'libraries = ["Servo@1.3.0"]\n[board]\n'
        f'fqbn = "{fqbn}"\ncore = "{fqbn.rsplit(":", 1)[0]}"\n'
        f'[stock]\nlocation = "{stock_location}"\nmain = "stock"\n'
        '[genie]\nskeleton = "genie/skeleton.ino"\n'
        'helpers = ["wave(n): wave n times"]\nkeys = ["ok", "cmd1"]\n'
        + (
            '[copy]\nask_placeholder = "Wave when I press OK"\n'
            '[[copy.suggestions]]\ntitle = "Wave"\nbehaviour = "shake"\n'
            '[[copy.suggestions]]\ntitle = "Wave twice"\nask = "wave two times when I press OK"\n'
            if copy
            else ""
        )
    )
    (b / "pins.toml").write_text("[pins]\nservo = 10\n[limits]\nangle = { min = 0, max = 180 }\n")
    (b / "hardware.md").write_text("# Test Box\nOne servo on pin 10.\n")
    (b / "concepts.toml").write_text(
        '[servo]\ntitle = "What is a servo?"\n'
        'explanation = "A motor that goes to an angle."\ntags = ["motor"]\n'
        'question = "Want to know how a servo moves?"\n'
        '[loop]\ntitle = "Repeating"\nexplanation = "A loop repeats."\n'
    )
    (b / "behaviours" / "shake.toml").write_text(
        'id = "shake"\ntitle = "Shake"\ndescription = "Press OK and it shakes."\n'
        'trigger = "key ok"\naction = "shake"\ntested = "compile-only"\nconcepts = ["servo"]\n'
    )
    (b / "behaviours" / "shake" / "shake.ino").write_text(SKETCH)
    (b / "templates" / "wave.toml").write_text(
        'id = "wave"\ntitle = "Wave"\ndescription = "Change the numbers."\n'
        'tested = "compile-only"\n'
    )
    (b / "templates" / "wave" / "wave.ino").write_text(SKETCH)
    # the box's own code carries the IDE's markers (P8 round 4): one in the main, two in config.h
    (b / "stock" / "stock" / "stock.ino").write_text(STOCK_MAIN)
    (b / "stock" / "stock" / "config.h").write_text(
        'int top = 100; // the top -- ///{"min":0,"max":200}\n'
        'bool flip = false; ///{"options":["true","false"]}\n'
    )
    return b


@pytest.fixture
def boxes_dir(tmp_path: Path) -> Path:
    root = tmp_path / "boxes"
    write_box(root)
    return root
