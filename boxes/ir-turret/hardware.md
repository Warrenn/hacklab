# IR Turret — hardware for the AI helper and the maintainer

A Nano-class board (ATmega328P) drives three servos and listens to an IR remote.

| Part | Pin | How it works | Safe use |
| --- | --- | --- | --- |
| Yaw servo (turns the whole turret) | 10 | Continuous rotation. `write(90)` = stop. `write(90 + speed)` turns one way, `write(90 - speed)` the other. Movement is timed: run for `yawPrecision` ms then stop. | speed 10–90, time 50–500 ms. Never leave it running. |
| Pitch servo (tilts up/down) | 11 | Positional. `write(angle)`. | angle 33–150, home 100. Outside this it crashes into the frame. |
| Roll servo (fires darts) | 12 | Continuous rotation. One dart = run at full speed for `rollPrecision` (~158 ms). Six darts = 6 × that. | 125–225 ms per dart. |
| IR receiver | 9 | NEC protocol via IRremote 4.x: `IrReceiver.decode()`, `IrReceiver.decodedIRData.command`, then `IrReceiver.resume()`. | — |

Remote keys (NEC command codes): left `0x8`, right `0x5A`, up `0x18`, down `0x52`,
OK `0x1C`, 1 `0x45`, 2 `0x46`, 3 `0x47`, 4 `0x44`, 5 `0x40`, 6 `0x43`, 7 `0x7`,
8 `0x15`, 9 `0x9`, 0 `0x19`, star `0x16`, hash `0xD`.

Stock helpers the kid can call: `leftMove(n)`, `rightMove(n)`, `upMove(n)`,
`downMove(n)`, `fire()`, `fireAll()`, `homeServos()`, `shakeHeadYes(n)`,
`shakeHeadNo(n)`. "Shaking the head" is yaw speed + time, not an angle.

Kid words: yaw = "turn", pitch = "tilt", roll = "fire". Six darts in the drum.
