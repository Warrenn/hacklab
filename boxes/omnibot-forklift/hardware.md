# Omnibot Forklift — hardware notes

Nano-class board. Three omni wheels on DC motors through direction + PWM pins,
a lift motor, and a 4-channel RF remote receiver read as digital inputs with
pull-ups. Wheel speeds come from a linear kinematics formula (wheel angles 90°,
210°, 330°). `config.h` exposes the tweakables: `maxSpeed` 0–255 and four
motor-flip booleans. Serial at 115200 prints the version banner `OMNIB V0.9.1`.

Stock sketch is user-supplied (no license header): keep it at
`data/boxes/omnibot-forklift/stock/StockCode/` on the device.
