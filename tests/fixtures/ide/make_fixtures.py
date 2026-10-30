"""One-off: turn raw editor dumps into the importer fixtures (kept for provenance).

ir-turret.json  : the MIT-licensed stock.ino + passcode.ino verbatim (headers kept).
synth-box.json  : a synthetic, unlicensed Forklift-shaped sketch (config.h, #define pins,
                  no IR switch) so the "device" placement and the loop-marker path are tested
                  without shipping CrunchLabs code that carries no license header.
"""

import json
from pathlib import Path

here = Path(__file__).parent
raw = {}
for f in ("turret-models.json", "turret-roulette.json"):
    p = here / f
    if p.is_file():
        raw.update(json.loads(p.read_text())["files"])
if raw:
    files = {}
    for uri, text in raw.items():
        name = uri.rsplit("/", 1)[1]
        assert "MIT License" in text and "Copyright" in text, name
        files[f"{name.removesuffix('.ino')}/{name}"] = text
    (here / "ir-turret.json").write_text(
        json.dumps({"slug": "ir-turret", "files": files}, indent=1) + "\n"
    )

SYNTH_INO = """\
/* Synthetic test sketch in the shape of a Forklift-style Hack Pack box: no license header. */
#include "config.h"

#define RF_S1_V 19       // receiver pair 1
#define RF_S1_G 18
#define M1_DIR 4
#define M1_PWM 5
#define LIFT_DIR 2
#define LIFT_PWM 3

int vSpeed[3];
int moveFork = 0;
double botRadius = 100.0;
unsigned long lastStrafe = 0;

void setup() {
  Serial.begin(115200);
  pinMode(RF_S1_V, INPUT_PULLUP);
  pinMode(M1_DIR, OUTPUT);
}

void loop() {
  getDirection();
  moveBot();
}

void getDirection() {
  moveFork = digitalRead(RF_S1_V) ? 0 : 1;
}

void moveBot() {
  digitalWrite(M1_DIR, moveFork > 0);
}
"""
SYNTH_CONFIG = (
    'uint8_t maxSpeed = 255; ///{"min":0,"max":255}\n'
    'bool flipM1 = false; ///{"options":["true","false"]}\n'
)
(here / "synth-box.json").write_text(
    json.dumps(
        {
            "slug": "synth-box",
            "files": {"StockCode/StockCode.ino": SYNTH_INO, "StockCode/config.h": SYNTH_CONFIG},
        },
        indent=1,
    )
    + "\n"
)
print("fixtures written")
