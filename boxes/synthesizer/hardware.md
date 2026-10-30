# Laser Synthesizer — hardware

A Nano runs a sound engine called Mozzi. It makes the sound itself on pin 9, so
`loop()` must stay empty apart from `audioHook()`; anything slow there makes the
sound crackle. All control logic runs in `updateControl()` 128 times a second.

- **Touchpad** (A0, A1, D7, D8): a flat pad you press. Up and down picks the
  note from the current scale; left and right sets how loud the second note is.
  Lifting your finger goes quiet.
- **Three knobs**: bottom (A5) picks the wave shape (Triangle, Square, Saw,
  Noise), middle (A6) picks the second note, top (A7) is the master volume.
- **Proximity sensor** (D6): sees a hand or the fidget spinner close by. A hand
  turns the volume down; spinning the spinner over it makes the sound wobble
  (an LFO) at the speed of the spin, and the wobble slowly fades when it stops.
- **Speaker**: driven by Mozzi on pin 9. Keep AUDIO_OUTPUT_BITS between 13 and
  15 and MASTER_GAIN_MAX at or below 64, or it distorts.

Safe to change: the default scale (0-11), root note (MIDI 24-108), default wave
(0-3), smoothing, LFO speeds. Do not change CONTROL_RATE (must be 128) or the
pin numbers.
