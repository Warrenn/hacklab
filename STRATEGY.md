# STRATEGY.md — Hack Lab (repo: hacklab)

Kid-facing "program your robot" system for CrunchLabs Hack Pack boxes. An
11-year-old with only an iPad asks in plain language for a behaviour ("make it
shake its head when I press 7"); a headless Raspberry Pi 3 at his home turns
that into code, compiles it, flashes the box over USB, and reports back in kid
language. When the AI is unavailable he can still pick, tweak, and flash
behaviours himself. Public GitHub repository.

Design rationale (the *why*) lives in the Claude doc "Hack Lab Design
Principles" (2026-10-28). This file is the *what* and *in what order*.

Scope change 2026-10-28: not only the IR Turret. Any Hack Pack box. The kid
currently owns the **IR Turret** and the **Laser Synthesizer** ("laser DJ").

## Principles (summary — see design doc)

1. **Robust and recoverable.** No irreversible states. "Back to a known-good
   box" is one action away with no AI and no internet. Maintainer visits are
   months apart, so remote state/updates are a requirement.
2. **Built for a 10-minute attention span.** One satisfying physical result
   per sitting. Reward = the box doing something + praise text. No points yet.
3. **Educational first.** Stage 1 magic genie → stage 2 guided editing →
   stage 3 he edits, AI helps. Mental model = "when ⟨trigger⟩ → ⟨action⟩";
   loops/conditions/timing/variables introduced by need.
4. **Easy to use, easy to see how it works.** Code visible on request;
   curiosity prompts (≤3) open short in-app explanations. **No external links
   of any kind in the MVP.** Levels borrow the Hack Pack IDE's own vocabulary:
   Level 1 = AI does it (default), Level 2 = change the numbers, Level 3 =
   edit all the code. Level 3 is always available, never the default.
   The AI is called "the AI helper" in the UI, with a visible
   "AI helper is here / away" status.
5. **Feedback everywhere.** To the kid: progress, praise, help. To the
   maintainer: a durable, remotely readable log of every request, sketch,
   compile and flash result.

## Non-negotiable constraints

1. **End user is a minor (11).** No Claude app / consumer account. Custom app
   on the Anthropic API with content filtering, logging (consent obtained),
   age-appropriate persona, hard monthly spend cap.
2. **iPad is his only device.** PWA at `http://hacklab.local`, no login, no
   installs. Dictation via the iPad keyboard mic (v1).
3. **Pi is headless at his home**, different city. Everything auto-starts and
   survives power cuts. Remote admin = AWS IoT Core (state, logs, updates) +
   Tailscale SSH (break-glass, root). No arbitrary remote command execution.
4. **Every change reversible.** Versioned sketch store per box; always-visible
   Undo and Back-to-original. Reset is **per box**.
5. **Works without the AI.** Offline behaviour library + template editing +
   compile + flash + reset must all work with no internet and no API key.
6. **Public repo hygiene.** No secrets or PII. CrunchLabs stock sketches are
   MIT (verified 2026-10-28) and are committed with their license headers.

## Hardware on hand

- Raspberry Pi 3 Model B v1.2, Raspberry Pi OS (64-bit) re-imaged 2026-10-27,
  hostname `hacklab`, user `admin`, keyboard us, SSH enabled.
- Official 2.5 A micro-USB supply ordered 2026-10-27. Earlier supplies gave
  `vcgencmd get_throttled` = 0x50005 and reboot loops once the WiFi radio came
  up. **Nothing else gets debugged until get_throttled reads 0x0.**
- Official 7" Touch Display (DSI) in a case, wired, currently black — parked.
- Boxes: IR Turret (Nano-class ATmega328P, 3 servos, IR receiver + remote)
  [VERIFY servo count/pins on unit]; Laser Synthesizer (touchpad synth +
  Bluetooth speaker + laser visualizer per CrunchLabs product page; board and
  I/O [VERIFY on unit — product page gives no hardware detail]).
- Every Hack Pack box with a public build write-up uses a Nano-compatible board
  over USB (Balance Bot, Turret, Domino Robot, Label Maker, Sand Garden, Laser
  Tag). Assumed for all 17 boxes [VERIFY per box]. Consequence: the Pi cannot
  identify a box over USB; the app has a box picker.

## Architecture

```
iPad Safari PWA ──HTTP+SSE (LAN)──> Pi backend (FastAPI, Python 3.11+)
                                      ├─ Box profiles (boxes/<id>/…): spec, pins,
                                      │    limits, library whitelist, behaviours,
                                      │    templates, concept explanations
                                      ├─ Offline path: pick behaviour / edit
                                      │    template → compile → flash → version
                                      ├─ Genie path: request + current sketch +
                                      │    box spec + persona → Anthropic API →
                                      │    full sketch → compile (retry on error,
                                      │    max N) → flash → curiosity prompts
                                      ├─ arduino-cli (arduino:avr) ──USB──> box
                                      ├─ Sketch store: versions per box, pinned
                                      │    known-good baseline per box
                                      ├─ Event log (JSONL, rotated) ─┐
                                      └─ Ops agent (separate process) ─┴─> AWS IoT
                                           Core: shadow (state), MQTT (logs),
                                           Jobs (signed updates)
Tailscale SSH (break-glass, root)
```

Rules:
- The offline path is the foundation; the genie calls the same compile/flash
  functions. If the API is unreachable or capped, the app degrades to offline
  mode with a friendly explanation, never an error wall.
- Never flash an uncompiled sketch. Never flash a sketch for box A while the
  picker says box B.
- The ops agent is independent of the app (own systemd unit, own venv) so a
  broken app never takes out remote visibility.

## Findings from the Hack Pack IDE (ide.crunchlabs.com, read 2026-10-28)

- **The IDE flashes via Web Serial** (`navigator.serial.requestPort()` in its
  bundle, read 2026-10-30), not the Arduino Create Agent as noted in
  September. There is no local agent endpoint to redirect to a Pi; flashing
  happens from the browser's own USB port. iPad Safari has no Web Serial and
  the IDE shows a tablet warning (`isTabletDevice`). Conclusion: the Hack Pack
  IDE cannot be used from the iPad in any configuration; Hack Lab must be the
  IDE for the iPad. The real IDE remains the fastest USB test harness on the
  Mac and the visual reference for the Level 3 editor.
- **Stock code is MIT-licensed** (IR Turret: "Copyright (c) 2025 Crunchlabs LLC
  (IRTurret Control Code)" + IRremote by Armin Joachimsmeyer; Laser
  Synthesizer: "Copyright (c) 2025 Crunchlabs LLC (Laser Synthesizer Code)").
  → Stock sketches CAN be committed under `boxes/<id>/stock/` with the license
  header intact. Supersedes the "user-supplied, untracked" rule.
- **Their Level 2 is an inline annotation convention** on a line's trailing
  comment: `///{"range":[10,90],"step":10}` or `///{"min":125,"max":225}`,
  e.g. `int yawMoveSpeed = 90; // … -- ///{"range":[10,90],"step":10}` and
  `upMove(1); ///{"range":[1,10]}`. → Adopt the SAME convention for our
  templates and behaviours: the Tweak screen parses `///{…}` markers; no
  separate `{{tweakable}}` syntax. Stock sketches then work as Level 2
  templates with zero editing.
- Sketches are organised with `#pragma region` blocks: LICENSE, LIBRARIES,
  IR CODES, PINS AND PARAMS, SETUP, LOOP, FUNCTIONS. → Box profile hardware.md
  and the genie's system prompt reference these regions; the editor can fold
  LICENSE/LIBRARIES by default.
- The IDE has a GUIDED on/off toggle and lock icons on regions — their
  Level 1/2 gating. Same idea as ours.
- Each box ships "hacks" (variants): IR Turret has `stock.ino`,
  `passcode.ino`, `roulette.ino`. → Seed the behaviour library with the
  official hacks (MIT) before writing our own.
- **IR Turret hardware (from stock.ino):** yaw servo pin 10 (continuous
  rotation: write 90 = stop, speed ± around 90, moves are timed by
  `yawPrecision` ms), pitch servo pin 11 (positional, clamped pitchMin 33 to
  pitchMax 150, home 100), roll servo pin 12 (continuous; `fire()` = run for
  `rollPrecision` ≈158 ms = one dart), IR receiver pin 9, NEC protocol. Remote
  codes: left 0x8, right 0x5A, up 0x18, down 0x52, ok 0x1C, 1–9/0 = 0x45 0x46
  0x47 0x44 0x40 0x43 0x7 0x15 0x9 0x19, star 0x16, hash 0xD. Libraries:
  Servo, IRremote (3.x API: `IrReceiver.decode()` / `.decodedIRData.command`).
  Built-in functions: leftMove, rightMove, upMove, downMove, fire, fireAll,
  homeServos, shakeHeadYes(n), shakeHeadNo(n). NOTE: "shake head" is yaw
  speed+time, not angle — the design mock's `pan.write(60/120)` is wrong;
  fix in P2 templates.
- **Laser Synthesizer:** `StockCode.ino` + `config.h`, `system_config.h`,
  `wavetables.h`, `scale_tables.h`; Mozzi audio library (stereo); pots on
  A5/A6/A7 (A6/A7 exist only on Nano-class boards → same flash path as the
  turret, certainty 8 [VERIFY by plugging it in]); touchpad X/Y, proximity
  sensor, "fidget spinner" LFO. Hacks: Cloud9ChordBuilder, DrumnBass5.
  → Flash core must handle **multi-file sketch folders**, not only one .ino.
- Newer boxes (NixieClock with a WifiSTA hack, ColorComposer, SpaceOddity,
  RobotRanger, RoboLamp, TankPlant, OmnibotForklift) are multi-file projects
  with `include/Configuration.h` and `src/` — PlatformIO-style, and at least
  NixieClock has WiFi, so probably ESP32-class. → Box profile needs a `board`
  field (fqbn + core); the "all Nano" assumption holds for the two boxes on
  hand, not for the whole range.

## Dev & deploy

**Docker is a dev-only stand-in for the Pi. No Docker on the Pi** (1 GB RAM,
needs USB + systemd anyway, one less layer to break unattended).

Mac (M4, arm64):
- `Dockerfile.dev`: `debian:bookworm` arm64 (native, no QEMU) running the SAME
  `provisioning/install-toolchain.sh` the Pi runs → Python venv, arduino-cli,
  `arduino:avr`, whitelisted libraries. `FAKE_BOARD=1`.
- `docker-compose.yml`: bind-mounts the repo, publishes :8000 so the iPad can
  open the PWA over home WiFi.
- `FAKE_BOARD` = serial backend that emulates a Nano (enumerate, accept upload,
  re-enumerate after delay, fail on command). Compiles are real; only upload is
  faked. The flash core takes the port backend as a dependency.
- Real flashing during dev: `arduino-cli upload` on the Mac host against the
  `.hex` the container built, or the Pi.
- OS-level work (systemd, comitup, rootfs, IoT provisioning) is shell scripts
  tested only on the real Pi.

Pi layout:
```
/opt/hacklab/
  releases/<version>/   immutable deployed versions
  current -> releases/… symlink the services run from
  venv/                 from install-toolchain.sh
  data/                 writable partition: sketch versions, logs, config.toml
systemd: hacklab-app.service, hacklab-ops.service (separate venv; app deploys
never restart it)
```
First install: clone + `provisioning/install.sh` (idempotent) on a visit or
over Tailscale. After that, no logins to deploy.

Release → signed job → agent:
1. CI on tag: `hacklab-<version>.tar.gz` (app, profiles, PWA,
   `manifest.json` with sha256 per file), signed with **minisign** (private key
   in GitHub secrets, public key baked onto the Pi), uploaded to private S3.
2. Maintainer creates an IoT Job: `{op: deploy, version, url (presigned S3),
   sig}`.
3. Ops agent: download to `releases/<version>/`, verify signature + checksums,
   `install.sh --release`, swap `current`, restart `hacklab-app`, poll
   `/api/status` 30 s.
4. Health fails → automatic rollback (symlink back, restart), job reports
   `failed` with log. Succeeds → `succeeded`, shadow updated with version.
5. Job allowlist, complete: `deploy`, `rollback`, `restart`, `upload-logs`,
   `report-state`, `apt-upgrade` (manual trigger only). No command execution.

Security property: the agent runs only code from a tarball whose minisign
signature verifies against the on-device public key, received over a channel
IoT Core already authenticated with the device certificate.

Decisions: minisign (no deps on Pi). First few releases uploaded to S3 by hand;
CI upload once the flow is proven.

## Maintainer scripts (how a deployment gets updated)

All under `scripts/`, idempotent, documented in README. The nephew's Pi is
updated only through these; nothing is hand-edited on the device.

| Script | Does | Typical trigger |
| --- | --- | --- |
| `new-box.sh <id> "<Name>"` | Scaffolds `boxes/<id>/` from a template profile (profile.yaml, hardware.md, pins.yaml, concepts.yaml, behaviours/, templates/, stock/README) | A new Hack Pack box arrives |
| `check-box.sh <id>` | Validates the profile, compiles every behaviour and template in Docker, lints kid-facing strings | Before committing a profile |
| `release.sh [version]` | Builds the signed tarball (app + PWA + all box profiles), writes manifest, uploads to S3; CI runs the same | Anything to ship: new box, new behaviour, bug fix |
| `deploy.sh <device> <version>` | Creates the IoT Job for that device; waits and prints the result (succeeded / failed + log) | After `release.sh` |
| `rollback.sh <device>` | IoT Job: switch `current` to the previous release | A bad release |
| `status.sh <device>` | Reads the device shadow: version, box selected, last flash, AI reachable, throttled state, disk, uptime | Any time |
| `logs.sh <device> [since]` | IoT Job `upload-logs`, then downloads the bundle from S3 | Investigating |
| `provision-device.sh <device>` | One-time: creates the IoT thing + cert, writes `provisioning/local/<device>/` (untracked) | New Pi |

A new box therefore costs: `new-box.sh` → fill the profile → `check-box.sh`
→ commit → `release.sh` → `deploy.sh`. The PWA reads `/api/boxes` so the
picker updates with no frontend change.

## Box profile schema (`boxes/<box_id>/`)

```
profile.yaml      id, name, picture, board {fqbn, core}, port hints, libraries,
                  sketch layout (single .ino or folder)
hardware.md       spec for the system prompt: actuators, sensors, inputs,
                  ranges, remote key map, safety limits (kid language + exact)
pins.yaml         pin map + clamp ranges enforced in code
behaviours/       <name>.ino + <name>.yaml (title, kid description, tweakables,
                  trigger/action tags, tested: date)
templates/        sketches using the IDE's `///{"range":[a,b],"step":s}` /
                  `///{"min":a,"max":b}` trailing-comment markers
concepts.yaml     concept id → kid explanation (2–4 sentences, no links),
                  tags used to pick curiosity prompts
stock/            the official stock sketch + hacks (MIT, headers kept)
```

MVP ships `ir-turret` complete and `laser-synth` as the proof that the
abstraction holds (profile + 3 behaviours + 1 template), once its hardware is
verified on the unit.

## API contract (PWA ↔ backend)

All JSON. Progress via SSE on `/api/events`.

```
GET  /api/status            {box, online, ai_available, board_connected,
                             current_version, versions_count}
GET  /api/boxes             [{id, name, picture}]
POST /api/box               {id}                → select active box
GET  /api/behaviours        [{id, title, description, tweakables}]
POST /api/flash/behaviour   {id, tweakables?}   → job_id
POST /api/flash/template    {template_id, values} → job_id
POST /api/flash/sketch      {source}            → job_id  (stage 3 editor)
POST /api/ask               {text}              → job_id  (genie)
GET  /api/jobs/{id}         {state: queued|thinking|compiling|uploading|
                             verifying|done|failed, message_kid, log_ref,
                             prompts: [{id, question}], sketch_ref}
POST /api/undo                                  → job_id
POST /api/reset                                 → job_id  (per active box)
GET  /api/sketch/current    {source, version, box}
GET  /api/concepts/{id}     {title, explanation}
SSE  /api/events            job progress + status changes
```

Kid-facing strings are generated server-side so the PWA stays dumb. Every job
writes one JSONL event with request, box, sketch hash, compile output, flash
result, duration, ai_used.

## Turn design (10-minute budget)

- A turn (model + compile + upload) is 20–60 s; a session is 5–10 turns.
- The waiting period is designed: live stage text ("thinking… compiling…
  uploading… watch it!"), with a stage-appropriate animation.
- The app opens with 3 pre-tested "try this" suggestions for the active box, so
  the first turn of a session always succeeds.
- On failure: kid-language message, one obvious next action (Try again /
  Undo / Back to original), never a stack trace.
- Correction = Undo + re-ask. No conversational correction in the MVP.

## Phases (foundation first)

**P0 — Repo scaffold.** Public repo, MIT, README, .gitignore, CLAUDE.md,
config.example.toml, CI (ruff + pytest). `provisioning/install-toolchain.sh`,
`Dockerfile.dev`, `docker-compose.yml` (arm64 bookworm, FAKE_BOARD=1). CI builds
the same image so "every behaviour compiles" runs on the Pi's toolchain. Mock
backend so P3 can be built on the Mac without a Pi.

**P1 — Flash core.** arduino-cli wrapper: compile, upload, port detection,
Nano old/new bootloader fallback [VERIFY on real board], re-enumeration
check, version store per box, reset-to-baseline. Port backend is injectable:
`RealBoard` (pyserial + arduino-cli upload) and `FakeBoard` (emulated Nano with
scripted failures). Unit tests run on FakeBoard; one HIL smoke script.

**P2 — Box profiles + offline path.** Profile loader/validator; `scripts/new-box.sh`
+ `check-box.sh`; `ir-turret` profile with ≥6 tested behaviours and ≥2 templates
derived from the stock sketch's own structure (constants at top, `switch` on IR
command → action functions), mirroring the Hack Pack IDE's Level 2 variables; template rendering with
range clamping; `/api/behaviours`, `/flash/*`, `/undo`, `/reset`. Tests:
profile validation, template clamping, every shipped behaviour compiles in CI.

**P3 — PWA.** Single-file HTML/CSS/JS, no build step, served by FastAPI. Screens
per the "Hack Lab Screens" design canvas (2026-10-28): box picker, home
(try-this + ask box), working (4-stage progress + one-line explanation), done
(praise + curiosity prompts + code with tweakables highlighted + Level 3 link),
Level 2 tweak (sliders + live code), home-with-AI-away (offline tricks grid).
Undo / Back-to-how-it-came identical on every screen. Level 3 = plain code
editor + Send, reachable but never default. Built against the P0 mock first.
Tests: Playwright against mock on iPad viewport.

**P4 — Genie.** Anthropic API client; system prompt = persona + box hardware.md
+ current sketch + rules; full-sketch output; compile-retry loop (max 3);
clarify-or-explain path for impossible/off-mission asks; curiosity prompt
selection from concepts.yaml; degrade to offline when unavailable/capped.
Tests: golden prompts with recorded responses; injected compile failures;
offline degradation.

**P5 — Provisioning & ops.** `install.sh` (idempotent; releases/current/venv/
data layout); systemd units (app, ops agent); comitup captive-portal fallback
(notes below); read-only rootfs + writable data partition; log rotation;
Tailscale; AWS IoT Core device provisioning (per-device cert, shadow, log
topic, Jobs) [VERIFY pricing/free tier, Python SDK on Pi 3 arm64]; ops agent
with the job allowlist, minisign verification, health check + auto-rollback;
CI release build + signing; spare pre-imaged SD.

**P6 — Laser Synthesizer profile.** Verify hardware on the unit; profile + 3
behaviours + 1 template; proves the abstraction.

**P7 — Hardening & field checklist.** Spend cap; guardrail red-team; persona
polish; family "if broken" card; on-site smoke test; box pictures for picker.

Decision 2026-10-30 — **HTTP only for the MVP** at `http://hacklab.local`
(mDNS via Avahi; same network segment as the iPad; backend on port 80 so no
port in the URL). Not a secure context, so: no service worker / offline PWA
caching, no in-page microphone (keyboard dictation unaffected). When the
in-app mic or installable PWA is wanted, the path is a real certificate via
own domain + Let's Encrypt DNS-01 (Route 53), A record to the Pi's private
LAN IP (DHCP reservation or self-updating record), renewal by the Pi or an
IoT job, `hacklab.local` kept as fallback. Check the home router for DNS
rebind protection. Self-signed + iPad trust profile rejected (fiddly, fails
"just works"); Tailscale certs are admin-only.

Deferred (recorded, not scheduled): physical reset button; points/levels;
block-based editor; curated external links; conversational correction;
HTTPS (see decision above); Android tablet running the CrunchLabs IDE directly
(Chrome Android 148+ has Web Serial) if the hardware situation ever changes;
touchscreen kiosk page; Bluetooth onboarding (rejected — needs native app).

## P6 plan — Every Hack Pack box, zero maintenance on arrival (approved 2026-10-30)

Replaces the single Laser Synthesizer profile with the general pipeline
(roadmap item above); the Laser Synth is its first proof once its hardware
is checked on the unit.

Goal: a new box becomes a content-only PR and a signed release, with no
login to the Pi: `scripts/import-box.sh <ide-slug>` pulls the stock code and
hacks from the Hack Pack IDE, scaffolds the profile, derives pins and
tweakables, builds the genie skeleton, and `check-box.sh` compiles it all;
boards other than the Nano get their core pre-installed and their upload
quirks handled by a board registry.

Decisions (to confirm):
- **Importer** = Playwright through the machine-wide `pw` harness driving
  `ide.crunchlabs.com/editor/<slug>` exactly as done by hand on 2026-10-30
  (Monaco editor models), writing `boxes/<id>/stock/<name>/` when a file
  carries an MIT header, else `provisioning/local/boxes/<id>/stock/` for the
  device. Deterministic: re-running updates in place and reports a diff.
- **Board registry** `provisioning/boards.toml`: per fqbn the core to
  install, the bootloader/cpu options to try, USB VID:PID list, whether the
  port re-enumerates on reset, upload timeout. `install-toolchain.sh`
  installs every core referenced by `boxes/*/profile.toml`; `board.py`
  reads the registry instead of `KNOWN_NANO` / `CPUS`. ESP32-class boxes
  are expected: `esp32:esp32` core, `esptool` upload, native-USB
  re-enumeration -- verified on a board when one arrives, not guessed.
- **Skeleton generation** from the stock sketch: markers after the last
  global declaration, at the top of `loop()`, before the first function
  after `loop()`; a box with an unusual layout gets its skeleton hand-tuned
  in the same PR.
- **Per-box UI copy** (`[copy]` in profile.toml: ask placeholder,
  suggestions) closes the first UI-backlog item as part of this phase.
- **CI matrix** compiles every box on every push (exists); cores cached in
  the dev image.
- Tests: importer against a saved IDE page fixture; registry-driven
  detection/upload option tests on FakeBoard; skeleton-marker placement on
  the two stock sketches on hand; Laser Synth profile end to end.
- Parallelism: importer (`scripts/import-box.*`, tests) vs board registry
  (`provisioning/boards.toml`, `hacklab/board.py`, `flash.py`) are
  file-disjoint -> two agents in worktrees, registry owner merges first.

Steps: 1 registry + toolchain cores; 2 importer; 3 skeleton generator +
per-box copy; 4 Laser Synth through the pipeline (hardware check on the
unit first); 5 release + deploy via P5c; 6 docs, PR.

## Progress — P6
- [x] Step 1 — board registry, cores in the toolchain (PR #12) — completed 2026-10-30
- [x] Step 2 — import-box importer with fixture tests (PR #13) — completed 2026-10-30
- [x] Step 3 — skeleton generator (in the importer); per-box copy in profiles and PWA (Forklift suggestions are plain asks; Try it follows the last trick); board spec wired through runner/status; profile fqbn validated against the registry — completed 2026-10-30
- [x] Step 4 — Laser Synthesizer profile via the pipeline (MIT stock, Mozzi@2.0.4, compiles on the Pi incl. the genie skeleton); turret gained roulette.ino — completed 2026-10-30
- [ ] Step 5 — shipped as release 0.3.0 to the Pi
- [ ] Step 6 — README, notes, PR merged

## P6 notes (2026-10-30)

- Pipeline proven end to end on `synthesizer`: `import-box.sh synthesizer --name
  "Laser Synthesizer"` wrote the MIT stock (StockCode + 4 headers), profile,
  pins/limits (33 `///{}` limits from config.h), skeleton with the four markers.
  Hand-edited after: pins (the importer only scans the main `.ino`, the synth's
  `#define`s live in `system_config.h`), kid hardware notes, 4 concepts, genie
  helpers, `[copy]`. Compiles on the Pi: StockCode and the skeleton (49% flash,
  71% RAM; Mozzi leaves little room, fragments must stay small).
- Re-running the importer on `ir-turret` refreshed the two stock sketches
  (whitespace only) and added the MIT `roulette.ino` as third stock sketch.
- Mozzi@2.0.4 (latest in the Library Manager index on the Pi, 2026-10-30) is
  whitelisted; `lib install` pulls its FixMath dependency itself.
- `hacklab-apply deploy` now runs the release's `install-toolchain.sh`
  (idempotent: cores from the registry, libraries from the whitelist, venv pip)
  before flipping `current`, so a box with a new library or core ships as a
  release with no login. Falls back to `pip install -e` for old bundles.
- Schema gotchas met: `pins.toml` values are pin numbers 0-21 (Nano analog pins
  by number: A0=14 ... A7=21); `[copy.suggestions]` use `title`/`ask`.
- Hardware check of the synth on the unit is still owed (box not on hand);
  the profile's safe ranges come from CrunchLabs' own `config.h` comments.
- Still open from the plan: ESP32 registry entry unverified until a board
  arrives; `pw test` needs the `"hacklab/tests/pwa/"` filter while agent
  worktrees exist.

## P5c plan — Signed updates via IoT Jobs (2026-10-30, approved: option B, signing key outside AWS)

Goal: the maintainer ships a new version with two commands and no login:
`scripts/release.sh` builds and signs a tarball and uploads it to S3;
`scripts/deploy.sh <device> <version>` creates an IoT Job; the ops agent on
the Pi downloads, verifies the minisign signature, installs into
`releases/<version>/`, swaps `current`, restarts the app, health-checks it
and rolls back on failure, then reports the job result. `rollback.sh`,
`logs.sh` and the job allowlist (`deploy`, `rollback`, `restart`,
`upload-logs`, `report-state`, `apt-upgrade`) complete the design in "Dev &
deploy". Read-only root stays deferred.

Verified 2026-10-30: `awsiot.iotjobs.IotJobsClient` is in the Pi's ops venv
(`subscribe_to_next_job_execution_changed_events`,
`publish_start_next_pending_job_execution`, `publish_update_job_execution`,
`UpdateJobExecutionRequest(thing_name, job_id, status, status_details,
expected_version)`, `JobStatus.IN_PROGRESS/SUCCEEDED/FAILED`); `aws iot
create-job --targets <thing arn> --document '<json>' --target-selection
SNAPSHOT --timeout-config inProgressTimeoutInMinutes=30`; `minisign -G -W`
(key without password), `-S -s key -m file -t comment` -> `file.minisig`,
`-V -p minisign.pub -m file`; minisign 0.12 in Pi OS apt, Homebrew on the
Mac. IoT Jobs: $0.0045 per remote action -- negligible.

Decisions:
- **CloudFormation** (owner's rule) `provisioning/releases.yaml`: a private
  S3 bucket `hacklab-releases-<account>` (versioning on, public access
  blocked, 90-day expiry for `logs/`), an IAM role `hacklab-device` trusted
  by `credentials.iot.amazonaws.com` (GetObject/ListBucket on `releases/*`,
  PutObject on `logs/${credentials-iot:ThingName}/*`, nothing else), and an
  IoT **role alias** `hacklab-device` pointing at it (1 h credentials). The
  device policy in `iot-device.yaml` gains the jobs topics
  (`$aws/things/<thing>/jobs/*`) and `iot:AssumeRoleWithCertificate` on the
  alias. **Option B (owner, 2026-10-30):** the Pi exchanges its existing
  certificate for short-lived role credentials through the IoT credentials
  provider (`awscrt.auth.AwsCredentialsProvider.new_x509`, verified in the
  ops venv) and reads/writes S3 directly -- no presigned URLs, no Roles
  Anywhere (would need our own CA for no gain), offline-Pi deploys work.
  Certificate deactivation revokes both MQTT and the credentials. Updating
  the device stack must keep the certificate: `provision-device.sh` uses
  `update-stack` with `UsePreviousValue` for the CSR when the stack exists
  (a regenerated CSR would replace the certificate).
- **Signing (owner, 2026-10-30, revised):** the maintainer must be able to
  work from any machine. One minisign key pair whose secret key is
  **passphrase-protected** (`minisign -G`, passphrase chosen by the owner,
  kept only in their password manager); the encrypted key file is backed up
  as SecureString `/hacklab/minisign/secret-key` (`device-secrets.sh
  backup-signing-key` / `restore-signing-key`). AWS access alone therefore
  cannot sign (needs the passphrase); losing the Mac loses nothing. Signing
  prompts for the passphrase (`release.sh` is run by a human). Public key
  committed as `provisioning/minisign.pub`, installed to
  `/opt/hacklab/minisign.pub` by `install.sh`. CI signing later would need
  its own key. README gets a "new maintainer machine" checklist: clone,
  `aws sso login`, `device-secrets.sh restore pi3`, `restore-key`,
  `restore-signing-key`, `brew install minisign awscli` (or apt), done --
  nothing in the workflow is tied to this Mac.
- **Key custody revised again (owner, 2026-10-30, while stepping away):** the
  passphrase was removed (`minisign -C -W`) so releases can be signed
  unattended by the maintainer's tooling; the unencrypted key file is the
  Parameter Store backup. Consequence, recorded deliberately: anyone with
  read access to `/hacklab/minisign/secret-key` in the Busyweb account can
  sign a release, so the AWS login (SSO + MFA) is now the single root of
  trust for both creating jobs and authoring code. Re-adding a passphrase
  later is `minisign -C -s ~/.minisign/hacklab.key` + `backup-signing-key`.
- **Downgrade guard:** `hacklab-apply deploy` refuses a signed manifest whose
  version is lower than the running release; `rollback` only steps to the
  previous release already on disk.
- **Release = `git archive` of a tag** (`hacklab/`, `boxes/`, `static/`,
  `provisioning/`, `scripts/`, `ops/`, `pyproject.toml`, `README.md`) +
  `manifest.json` (version, git sha, built-at, sha256 per file) ->
  `hacklab-<version>.tar.gz` + `.minisig`, uploaded to
  `s3://<bucket>/releases/<version>/`. Version = the tag (`v0.1.0` ->
  `0.1.0`) or an explicit argument for untagged test builds.
- **Job document:** `{"op": "deploy", "version": "..."}` (the agent derives
  the S3 keys `releases/<version>/hacklab-<version>.tar.gz` + `.minisig`
  from the version); `rollback`, `restart`, `upload-logs` (agent uploads to
  `logs/<thing>/<ts>.tar.gz`), `report-state`, `apt-upgrade`. Anything else -> job REJECTED. The op allowlist is a dict
  in the agent; there is no command field.
- **Privilege split on the Pi:** the agent (user `hacklab-ops`) downloads to
  `/opt/hacklab/releases/<version>.tar.gz` (it owns `releases/`) and
  verifies the signature; the privileged part is one root helper
  `/opt/hacklab/bin/hacklab-apply` (installed by `install.sh`, allowed via
  `/etc/sudoers.d/hacklab-ops` NOPASSWD for exactly `hacklab-apply *`):
  `apply <version>` re-verifies the signature, extracts, `pip install -e
  releases/<version>` into the app venv, points `current` at it, restarts
  `hacklab-app`, polls `/api/status` on :80 for 60 s and on failure rolls
  back (previous `current`, reinstall, restart) and exits non-zero with the
  reason; `rollback` and `restart` likewise; `apt-upgrade` runs
  `apt-get upgrade -y`. Nothing in the job document is ever executed.
- **Agent:** on connect subscribes to next-job-changed, starts the next
  pending job, reports IN_PROGRESS with step details, runs the op in a
  thread, reports SUCCEEDED/FAILED with `status_details` (reason, release,
  health), updates the shadow (`release` now reads the `current` target,
  `last_job`). Heartbeat unchanged.
- **Maintainer scripts** (`scripts/`): `release.sh [version]`, `deploy.sh
  <device> <version>` (creates the job, waits, prints the execution status
  and details), `rollback.sh <device>`, `logs.sh <device>` (job + download
  the bundle to `provisioning/local/<device>/logs/`), `restart.sh`
  folded into `deploy.sh --restart`. `status.sh` shows `release` and
  `last_job`.
- Tests: agent job dispatch with a fake jobs client and fake downloader
  (allowlist, rejection, progress/terminal updates, signature failure never
  calls the helper); minisign wrapper against real `minisign` when present
  (skip otherwise); `release.sh` builds a tarball + manifest in a temp dir
  and its signature verifies; `hacklab-apply --dry-run`; shellcheck on all;
  cfn-lint; `tests/test_boxes_compile.py` unchanged. HIL: the real loop on
  the Pi (below).
- Parallelism: AWS/scripts (`provisioning/*.yaml`, `scripts/*.sh`) vs
  agent (`ops/agent.py`, tests) are file-disjoint; serialized, same session.

Steps:
1. Keys + AWS: minisign key pair (file + Keychain, not AWS), public key
   committed; `releases.yaml` stack (bucket, device role, role alias) and
   the device policy update (jobs topics + AssumeRoleWithCertificate) via
   CloudFormation keeping the certificate; `install.sh` installs the public
   key, the `hacklab-apply` helper, the sudoers rule, `minisign` from apt,
   and the role-alias/bucket settings for the agent.
2. Tests red: `tests/test_ops_jobs.py` (dispatch, allowlist, progress,
   signature failure, rollback result), `tests/test_release.py`
   (`release.sh --dry-run` tarball + manifest + signature verify).
3. `ops/agent.py` jobs handling + `ops/minisign.py` wrapper;
   `provisioning/hacklab-apply`; `scripts/release.sh`, `deploy.sh`,
   `rollback.sh`, `logs.sh`; green, shellcheck, cfn-lint.
4. Pi: `install.sh` re-run (helper, sudoers, pubkey); `release.sh 0.1.0`
   from the Mac; `deploy.sh pi3 0.1.0` -> job SUCCEEDED, app serving from
   `releases/0.1.0`, `status.sh` shows it; deploy a deliberately broken
   build (`release.sh 0.1.1-bad` with a syntax error) -> health fails ->
   automatic rollback -> job FAILED with the reason, app still up;
   `rollback.sh` / `logs.sh` exercised; bogus job op -> REJECTED.
5. README (release flow), P5 notes, hygiene (no bucket account id, no key
   material), PR, merge; Pi follows main and from then on only releases.

## Progress — P5c
- [x] Step 1 — passphrase-protected signing key (encrypted backup in Parameter Store), releases stack (bucket, device role, role alias), device policy updated keeping the certificate, install.sh additions — completed 2026-10-30
- [x] Step 2 — tests written (red) — completed 2026-10-30
- [x] Step 3 — ops/jobs.py executor, ops/awsio.py (IoT credentials -> S3, minisign, sudo helper), JobsWorker in the agent, hacklab-apply, release/deploy/rollback/logs scripts; 162 tests, shellcheck, cfn-lint — completed 2026-10-30
- [x] Step 4 — Pi: 0.1.0 exposed macOS metadata in the tarball (health failed, auto-rollback kept the app up), 0.1.1 and 0.1.2 SUCCEEDED, 0.1.2-bad FAILED with automatic rollback, rollback.sh back to 0.1.1, logs.sh bundle fetched, downgrade to 0.1.0 refused, bogus op FAILED as rejected — completed 2026-10-30
- [x] Step 5 — README, notes, PR #11 merged; release 0.2.0 cut from main and deployed — completed 2026-10-30

## Remote-UI policy plan (2026-10-30, awaiting approval)

Goal: the owner's P5 notes on remote use over Tailscale, built: requests from
the Tailscale side see the same UI read-only, an explicit admin toggle
(gated on source, not a password) enables remote flashing, the kid's screen
shows "Uncle is helping" while it is on, and every remote action is logged
with `source=tailscale`.

Decisions:
- Source classification server-side from the peer address: Tailscale =
  100.64.0.0/10 or fd7a:115c:a1e0::/48 -> `remote`; everything else
  (home LAN, the setup hotspot 10.41.0.0/24, localhost) -> `local`. One
  function, `hacklab/remote.py`, unit-tested on addresses. The mock backend
  (`FAKE_BOARD=1`, no hardware) additionally honours an `X-Hacklab-Source`
  header so the browser tests can act as a remote viewer; the real runner
  never reads that header.
- Write endpoints (`/api/flash/*`, `/api/ask`, `/api/undo`, `/api/reset`,
  `/api/box` select) from a `remote` source return 403 with
  `{"detail": "Remote view only. Turn on helping to make changes."}` unless
  helping is on. Reads (`status`, `boxes`, `behaviours`, `jobs`, `sketch`,
  `concepts`, `events`) are always allowed.
- Helping toggle: `POST /api/helping {on: bool}` accepted only from a
  `remote` source (local callers get 403: the toggle never exists on the LAN
  side, matching "gated on the source interface"). Server-wide state with a
  2-hour auto-off; `GET /api/status` gains `helping: bool` and `source:
  "local"|"remote"`; a status event goes out on `/api/events` when it flips.
- PWA: when `source == "remote"` show a "Remote view" banner with the
  helping switch (also honour `?admin=1` on load by calling the toggle);
  while `helping` is true every client shows the line "Uncle is helping"
  under the header (the kid-facing copy the owner chose; no name). Write
  buttons disabled with the banner when remote and not helping.
- Logging: jobs record `source` in their JSONL event and ask log; the
  helping flips are logged to `data/helping.jsonl` with the peer address.
- No new dependencies; no password. Parallelism: API (`hacklab/`, tests)
  and PWA (`static/`, `tests/pwa/`) are file-disjoint; small enough to
  serialize in one branch.

Steps:
1. Tests red: `tests/test_remote.py` (classification), `tests/test_api_remote.py`
   (403s, toggle only from remote, status fields, auto-off via injected clock,
   events on flip, job/ask logs carry `source`, mock header honoured only in
   mock mode).
2. `hacklab/remote.py` + app wiring; green.
3. PWA banner, switch, `?admin=1`, "Uncle is helping" line; `pw` tests via
   the mock header (browser-testing skill); screenshots.
4. Pi: deploy; from the Mac over Tailscale (`http://hacklab/`): write blocked,
   toggle on, real ask flashes the Forklift, LAN view (`http://hacklab.local/`)
   shows the helping line, logs show `source=tailscale`; toggle off blocks
   again.
5. README, notes, PR, merge; Pi follows main.

## Progress — remote UI
- [x] Step 1 — tests written (red) — completed 2026-10-30
- [x] Step 2 — remote.py + app wiring green (149 tests) — completed 2026-10-30
- [ ] Step 3 — PWA banner, switch, helping line, pw tests
- [x] Step 4 — verified on the Pi from the Mac: remote writes 403, LAN cannot toggle, toggle from Tailscale, LAN status shows helping, real ask over Tailscale flashed the Forklift (57 s) and undo, off blocks again, asks.jsonl source=tailscale, helping.jsonl peers — completed 2026-10-30
- [x] Step 5 — README, notes, PR #10 merged — completed 2026-10-30

## P5b plan — Appliance (2026-10-30, awaiting approval)

Owner's choices 2026-10-30: P5 in two halves -- (A) appliance now, verify on
the Pi, then (B) signed updates via IoT Jobs; read-only root filesystem
deferred to a re-image with physical access (install.sh stays ready for the
two-partition layout; procedure documented).

Goal: a fresh Pi becomes the appliance with one script: the app runs as a
service on port 80 (`http://hacklab.local` from the iPad, no port), survives
reboots and power cuts, logs rotate, the API key lives in a root-only env
file, the ops agent keeps reporting, and the captive-portal fallback hands
port 80 back and forth cleanly.

Verified on the Pi 2026-10-30: `comitup-web` is inactive while connected;
comitup's `web_service:` option disables the named unit in hotspot mode and
enables it when WiFi is up (the unit must be left disabled in systemctl so
comitup owns it) -- that is the port-80 hand-off. `logrotate` is installed;
`minisign` 0.12 is in apt (for B). No `hacklab` user yet; `/opt/hacklab/*`
is root-owned.

Decisions:
- Layout (unchanged from Dev & deploy): `/opt/hacklab/{bin,arduino,venv,
  ops,data,src}`; `current -> src` for now (B swaps it to `releases/<v>`).
  Everything the services write goes under `/opt/hacklab/data` (sketch
  versions, logs, spend, device stock/skeletons, work dir) so a future
  writable partition mounts there.
- Service user `hacklab` (system, groups `dialout` for USB, owns
  `/opt/hacklab/arduino` and `/opt/hacklab/data`; `src`/`venv` root-owned,
  world-readable). The ops agent stays as `hacklab-ops`.
- `hacklab-app.service`: `uvicorn hacklab.app:app --host 0.0.0.0 --port 80`
  from `/opt/hacklab/venv`, `WorkingDirectory=/opt/hacklab/current`,
  `AmbientCapabilities=CAP_NET_BIND_SERVICE`, `EnvironmentFile=
  /etc/default/hacklab` (root:root 0600: `ANTHROPIC_API_KEY`,
  `HACKLAB_DATA_DIR`, `HACKLAB_BOXES_DIR`), `Restart=always`, `After=
  network-online.target`, hardening (`NoNewPrivileges`, `ProtectSystem=
  strict` with `ReadWritePaths` = data + arduino, `PrivateTmp`). NOT enabled
  in systemctl: comitup starts/stops it via `web_service`.
- `config.toml` for the appliance at `/etc/hacklab/config.toml` (port 80,
  data_dir, boxes_dir); `load_config` gains `HACKLAB_CONFIG` env.
- Logging: app stdout -> journald (`SystemMaxUse=200M`); JSONL logs under
  data rotated weekly by `/etc/logrotate.d/hacklab` (keep 8, compress).
- `provisioning/install.sh` (idempotent, root, run from a clone at
  `/opt/hacklab/src`): apt deps (git, python3-venv, logrotate, avahi),
  `install-toolchain.sh`, users, dirs + ownership, device stock/skeleton
  dirs, `/etc/default/hacklab` (created 0600 if absent; key filled from
  `HACKLAB_API_KEY` env or left for `scripts/push-key.sh`), config, units,
  logrotate, journald limit, comitup `web_service`, NM PMF fix file,
  `install-ops.sh` remote block folded in. Prints a health summary.
- `scripts/push-key.sh <ssh-target>`: pushes `ANTHROPIC_API_KEY` from `.env`
  into `/etc/default/hacklab` over Tailscale (never through git).
- Health: `GET /api/status` on :80 from the Mac at `http://hacklab.local`,
  the PWA loads, ask works (real genie), Forklift HIL via the service, power
  cut -> both services back, hotspot test -> comitup takes :80, home WiFi ->
  app takes :80 again.
- Tests: `install.sh` via shellcheck + a `--dry-run` that prints the plan
  (no root needed); unit files validated with `systemd-analyze verify` on
  the Pi; `load_config` HACKLAB_CONFIG test; `tests/test_api.py` unchanged.
- Parallelism: single track (shell + one config test); serialized.

Steps:
1. Config: `HACKLAB_CONFIG` env in `load_config` (test first); appliance
   `provisioning/config.toml`.
2. `provisioning/install.sh` + `hacklab-app.service` + logrotate + journald
   drop-in + `scripts/push-key.sh`; shellcheck; `--dry-run` locally.
3. Pi: run `install.sh` over Tailscale, push the key, verify
   `systemd-analyze verify`, service active on :80, `http://hacklab.local`
   from the Mac (status, PWA), real ask through the service with the
   Forklift (`hil-ask.sh` variant against :80), Undo.
4. Resilience on the Pi: power cut (owner pulls the plug) -> services back,
   heartbeat resumes; hotspot fallback -> comitup on :80 -> rejoin -> app
   back on :80 (comitup `web_service`).
5. README (fresh-Pi install, key push, re-image procedure for the
   two-partition layout), P5 notes, hygiene, PR, merge; Pi follows main.

## Progress — P5b
- [ ] Step 1 — HACKLAB_CONFIG + appliance config.toml
- [ ] Step 2 — install.sh, unit, logrotate, journald, push-key.sh (lint + dry run)
- [x] Step 3 — installed on the Pi (install.sh idempotent, 3 runs), app as `hacklab` on :80, PWA + API at http://hacklab.local from the Mac, real ask through the service 56 s, Undo 46 s — completed 2026-10-30
- [x] Step 4 — power cut (ssh 60 s, all 5 units active, :80 from the Mac, heartbeat at boot+44 s) and hotspot hand-off (comitup-web up, app stopped, portal served to the phone, app back on :80 59 s after rejoin) verified — completed 2026-10-30
- [x] Step 5 — README, notes, PR #9 merged — completed 2026-10-30

## P4 plan — Genie (the AI helper) (2026-10-30, approved incl. the fragments deviation)

Goal: a plain-language request from the kid becomes a compiled, flashed
sketch via the Anthropic API, with a compile-retry loop, a clarify-or-explain
path for impossible or off-mission asks, curiosity prompts from the box's
concepts, a hard monthly spend cap, and clean degradation to offline when the
API is unavailable or capped. Owner's choices 2026-10-30: dedicated API key
in `.env` (live calls allowed for recording goldens), `claude-sonnet-5-5`,
raw Messages API one call per turn (open decision 1 closed).

Verified 2026-10-30 (claude-api skill, live docs): `anthropic` 2.3.0 (pure
Python, Python >= 3.10); structured JSON via `client.messages.parse(...,
output_format=PydanticModel)` -> `response.parsed_output`; adaptive thinking
is the default on Sonnet 5.5 (never send `budget_tokens` or
`thinking.disabled`), depth via `output_config.effort`; prompt caching with
`cache_control` on the stable system block; usage fields
`input_tokens`/`output_tokens`/`cache_read_input_tokens`/
`cache_creation_input_tokens`; Sonnet 5.5 is $2 / $10 per MTok (cache reads
$0.20); refusals arrive as `stop_reason == "refusal"`, not exceptions; no
assistant prefill. Fallbacks to another model are NOT enabled: a refusal
means "not for this app", and the kid gets the offline path.

**Deviation to approve: the genie writes rule fragments, not a whole sketch.**
The P4 line says "full-sketch output". A full turret sketch is ~4k output
tokens, i.e. 40-60 s of generation before compile + flash even starts, which
blows the 20-60 s turn budget. Instead each box ships a *skeleton* (its stock
sketch with four insertion points: `//@@PARAMS`, `//@@CASES`, `//@@LOOP`,
`//@@FUNCTIONS` -- exactly how the P2 behaviours were generated) and the
genie returns only the fragments for those points (a few hundred tokens,
5-10 s). Setup, pins and library includes stay fixed, which is also the
safety property (the model cannot re-pin servos or add libraries). The
"when <trigger> -> <action>" mental model maps 1:1 onto `//@@CASES`. Level 3
(whole-sketch edits by the kid) is unaffected. The skeleton lives beside the
stock code: `boxes/<id>/genie/skeleton.ino` when the license allows (turret),
else `data/boxes/<id>/genie/skeleton.ino` on the device (forklift).

Decisions:
- `hacklab/genie.py`: `Genie(client, model, box)`; `ask(request,
  current_fragments, compile_error=None) -> GenieResult` with a Pydantic
  `GenieResult {kind: sketch|clarify|explain, params, cases, loop, functions,
  message_kid, changed, concepts[]}`. System prompt = persona (the AI helper,
  age-appropriate, kid words from hardware.md, no links, never asks for
  personal details, declines off-mission asks with `explain`) + rules + the
  box's hardware.md + helper function list + the skeleton, all stable ->
  one `cache_control` block. User turn = current fragments + request (+ the
  compiler error excerpt on a retry). `output_config.effort = "medium"`,
  `max_tokens` 8000, non-streaming (output is small).
- `hacklab/skeleton.py`: `assemble(skeleton, fragments) -> source`; fragments
  of the *current* version are stored in `data/<box>/versions/NNNN/
  fragments.json` so the next ask edits what the kid already has; Undo/Reset
  keep working unchanged (they flash stored sketch dirs).
- Compile-retry: the runner's `ask` job = thinking -> assemble -> flash;
  if the flash fails at `compiling`, re-ask with the error (max 3 attempts),
  then fail with the kid message. `clarify`/`explain` end the job as `done`
  with no flash and the model's question/explanation as `message_kid`
  (the PWA already shows `message_kid` on Done).
- Curiosity prompts: `GenieResult.concepts` filtered to the box's concept
  ids -> `prompts [{id, question}]`; `question` is a new optional field in
  concepts.toml (default "Want to know how <title>?"). Max 3.
- Spend cap: `hacklab/spend.py` appends every call's usage + cost (price
  table for the configured model) to `data/spend/YYYY-MM.jsonl`; month total
  >= `monthly_cap_usd` -> genie disabled until next month. `ai_available` =
  key present AND under cap AND not in a 10-minute "away" backoff after an
  API/network error. `/api/ask` returns 409 with the kid message when away.
- Every ask writes one JSONL event (request, box, result kind, sketch hash,
  attempts, usage, duration) to `data/<box>/logs/asks.jsonl` -- the
  maintainer's remote log (uploaded by the P5 `upload-logs` job later).
- Dev without hardware: `HACKLAB_BOARD=fake` runs the real runner + store +
  genie on `FakeBoard` (compiles are faked). `FAKE_BOARD=1` stays the PWA
  mock (FakeJobRunner, no API).
- Parallelism: content (turret skeleton, concept questions) vs code are
  file-disjoint but tiny; serialized.

Steps:
1. Content: `boxes/ir-turret/genie/skeleton.ino` (+ `profile.toml [genie]`
   helpers list), `question` per concept; forklift skeleton written on the
   Pi from its stock code (untracked). Hand-written golden responses in
   `tests/golden/*.json` for: shake on 7, fire when 3 pressed, an impossible
   ask ("make it fly"), an off-mission ask, a compile-error retry.
2. Tests red: skeleton assembly; GenieResult parsing from goldens via a
   fake client; system prompt contains the safety rules and hardware;
   spend ledger + cap; runner `ask` (retry on compile error, clarify ends
   without flash, API error -> away); `/api/status.ai_available`,
   `/api/ask` 409 when away/capped, prompts in the job.
3. `genie.py`, `skeleton.py`, `spend.py`, runner + app wiring; green, ruff.
4. Live: `scripts/record-golden.py` re-records the goldens with the real
   key (5 calls, cents); tests green on real responses; check
   `cache_read_input_tokens > 0` on the second call.
5. Pi: pull, install `anthropic` in the venv, key via a root-only
   `/etc/default/hacklab` (never in git), forklift skeleton on the device;
   HIL: `scripts/hil-ask.sh omnibot-forklift "lift the fork every 5 seconds"`
   through the real app -> compiled, flashed, serial banner; then Undo.
6. README (AI helper, spend cap, goldens), P4 notes, hygiene (no key, no
   nephew details, no prompts with personal data), PR, merge; Pi follows main.

## Progress — P4
- [x] Step 1 — turret skeleton + [genie] profile section, concept questions, 5 hand-written goldens (forklift skeleton lands on the Pi in Step 5) — completed 2026-10-30
- [x] Step 2 — tests written (red) — completed 2026-10-30
- [ ] Step 3 — genie, skeleton, spend, runner + app wiring green
- [x] Step 4 — 4 goldens re-recorded live on the Pi with real compiles (both sketches compile); cache_read 7643 tokens from the 2nd call; impossible and off-mission asks answered in kid language — completed 2026-10-30
- [x] Step 5 — Pi: live ask on the Forklift through the real app: timed lift rule generated with labelled tweak markers, compiled, flashed, serial banner, prompts, Undo; 51 s turn, $0.013 (cache hit 9384 tokens) — completed 2026-10-30. Service-level key install belongs to P5 install.sh
- [x] Step 6 — README, notes, PR #8 merged — completed 2026-10-30

## Sequencing change 2026-10-30: P3 runs in parallel with P1

Owner's call after asking whether the UI was being neglected: the PWA (P3)
is pulled forward and built against the P0 mock backend while P1 proceeds.
The two are file-disjoint (`static/` vs `hacklab/` + `tests/`); shared files
are STRATEGY.md, README.md and the one-line static mount in `hacklab/app.py`,
owned by the P1 track. Real flashing plugs in under the same API when P1/P2
land. P2 (profiles) follows P1 as before.

## P2 plan — Box profiles + offline path (2026-10-30, approved in advance by the owner; one deviation flagged)

Goal: everything box-specific moves out of code into `boxes/<id>/`; the
offline path (pick a trick / change the numbers -> compile -> flash -> version)
works end to end on the Pi with the real flash core. Ships `ir-turret`
complete (stock + official hacks, >=6 behaviours, >=2 templates, concepts) and
a minimal `omnibot-forklift` profile (board + pins + hardware notes; stock
sketch stays user-supplied and untracked because it carries no license).
`laser-synth` waits for its hardware check (unchanged).

Decisions:
- **Deviation: TOML, not YAML.** Python has `tomllib` in the stdlib and the
  repo already uses TOML for config; YAML would add a dependency for no gain.
  Files: `profile.toml`, `pins.toml`, `concepts.toml`, `behaviours/<id>.toml`
  (+ `<id>/<id>.ino` sketch dir), `templates/<id>.toml` (+ sketch dir),
  `hardware.md`, `stock/<Name>/...`. Owner may veto; then PyYAML.
- Stock sketch location: `stock/` in the repo when the license allows (turret:
  MIT header), else `data/boxes/<id>/stock/` on the device (untracked); the
  profile says which (`stock = "repo" | "device"`). Baseline = that dir.
- Tweakables: the IDE's trailing-comment markers only. Parser finds
  `///{...}` JSON on a line, the tweakable is the first numeric/boolean/string
  literal before the marker on that line; `range`/`min`+`max`/`step`/`options`
  forms; render = replace that literal, clamped to range and snapped to step,
  `options` must match exactly. Behaviours expose their markers as
  `tweakables[]` (name = the variable or a `"name"` key in the marker),
  templates likewise -- one engine for both; a template is a behaviour whose
  whole point is its numbers.
- Behaviours derive from the stock sketch's own structure (constants at top,
  `switch` on IR command -> action functions), matching the Offline screen's
  trick list: shake-head, nod-yes, lighthouse-spin, look-and-fire, guard-mode,
  fire-all, plus the official hacks (passcode, roulette) as behaviours too.
  Known fix from the IDE findings: yaw is speed+time, never `pan.write(angle)`.
  "tested" = compiles for `arduino:avr:nano` in CI (no turret on hand);
  marked `tested = "compile-only"` until flashed on a real turret.
- `hacklab/profiles.py`: load + validate all `boxes/*`, typed dataclasses,
  clear errors (missing file, bad marker, unknown library, pin out of range).
  App reads boxes/behaviours/concepts/stock from it; `mock_data.py` is
  deleted; `FakeJobRunner` stays for the PWA dev loop (`FAKE_BOARD=1`).
- API additions within the contract: `tweakables[]` items gain optional
  `options`; `/api/flash/behaviour` renders then flashes; `/api/flash/template`
  likewise; `/api/sketch/current` unchanged. Never flash for box A while the
  picker says B -- the job carries the box id and the profile check happens at
  submit.
- `scripts/new-box.sh <id> "<Name>"` scaffolds from `boxes/_template/`;
  `scripts/check-box.sh <id>` validates the profile, compiles every behaviour
  and template (Docker on the Mac/CI, native toolchain on the Pi), lints
  kid copy (no emoji, no URLs, "the AI helper"). CI runs `check-box.sh` for
  every box.
- Parallelism: content (`boxes/ir-turret/*`) and code (`hacklab/profiles.py`,
  `templates.py`, app, tests) are file-disjoint, but the content must compile
  against the engine's marker rules and the P3 agent already occupies the
  parallel slot; serialized in the main session.

Steps:
1. Content in: IR Turret `stock.ino`, `passcode.ino`, `roulette.ino` from the
   Hack Pack IDE (MIT headers kept) -> `boxes/ir-turret/stock/`; hardware.md
   and pins from the stock sketch + IDE findings. Forklift profile skeleton.
2. Tests red: `tests/test_profiles.py` (load, validate, errors),
   `tests/test_templates.py` (marker parse, render, clamp/snap, options,
   bad marker), `tests/test_api_profiles.py` (boxes/behaviours/concepts from
   disk, flash/behaviour renders + flashes via FakeBoard, box mismatch 409),
   `tests/test_boxes_compile.py` (every behaviour/template compiles; skipped
   unless `HACKLAB_CLI` points at a toolchain -- runs in the Docker CI job).
3. `hacklab/profiles.py`, `hacklab/templates.py`, app wiring, delete
   `mock_data.py`; green, ruff.
4. `boxes/ir-turret/` behaviours (8) + templates (2) + concepts; all compile
   in Docker; `scripts/new-box.sh`, `check-box.sh`, CI step.
5. On the Pi: pull, `check-box.sh ir-turret` natively; HIL with the Forklift
   profile (`stock = "device"`): offline path select -> behaviour flash is
   N/A without turret hardware, so the Forklift HIL re-runs `hil-flash.sh`
   through the profile-backed app (baseline from the device stock dir).
6. README (boxes, new-box, check-box), P2 notes, hygiene (no nephew details,
   stock headers intact), PR, merge; Pi follows main.

## Progress — P2
- [x] Step 1 — turret stock + passcode hack in (MIT headers kept; roulette did not load from the IDE, follow-up), hardware.md, pins, concepts, forklift skeleton — completed 2026-10-30
- [x] Step 2 — tests written (red) — completed 2026-10-30
- [ ] Step 3 — profiles.py, templates.py, app wiring green, mock_data removed
- [ ] Step 4 — ir-turret behaviours/templates/concepts compile; new-box.sh, check-box.sh, CI
- [x] Step 5 — Pi: check-box.sh ir-turret (11 compile tests, 3 min) and omnibot-forklift, Forklift HIL flash/undo/flash/reset through the profile-backed app — completed 2026-10-30
- [x] Step 6 — README, notes, PR #5 merged — completed 2026-10-30

## P3 plan — PWA (2026-10-30, pulled forward; approved, agent started on feat/p3-pwa)

Goal: the kid-facing app, built from the six screen specs in `docs/screens/`
against the P0 mock backend, so the owner can click through the whole loop on
the Mac before real flashing exists. Single-file `static/index.html` (HTML +
CSS + JS, no build step, no framework, no external links), served by FastAPI
at `/`; installable PWA (manifest + minimal service worker for the app shell
only; API calls are never cached). iPad Safari is the target.

Decisions:
- One file, one screen router keyed on app state (`picker`, `home`, `offline`,
  `working`, `done`, `tweak`); state comes only from the API contract:
  `/api/status`, `/api/boxes`, `/api/behaviours`, `/api/jobs/{id}`, SSE
  `/api/events`. The PWA invents no copy of its own: stage text and
  kid messages arrive from the server (`message_kid`); screen chrome copy is
  copied verbatim from the `.dc.html` specs.
- Offline screen is chosen by `ai_available=false`; Box Picker by
  `box=null`; Working by a non-terminal job; Done by a `done` job.
- Tweak sliders are bound to `tweakables[]` from `/api/behaviours` (name,
  value, range, step) and post to `/api/flash/behaviour`; the `options` form
  seen on the Forklift's config.h renders as a toggle. Live code panel shows
  `/api/sketch/current` with the tweakable numbers highlighted.
- Mic = iPad keyboard dictation into the textarea (design decision); no Web
  Speech API.
- Hygiene: no emoji, "the AI helper", "Level 1/2/3", no external links,
  no tracking. Box pictures come from `/static/boxes/<id>.png` (placeholder
  SVGs for now).
- Tests: Playwright through the machine-wide `pw` harness (browser-testing
  skill) against `uvicorn hacklab.app:app` with the mock runner: picker ->
  home -> ask -> working stages via SSE -> done -> undo; offline screen when
  `ANTHROPIC_API_KEY` is unset; tweak slider clamps to range; iPad viewport.
  No project-local Playwright install.
- Parallelism: see Parallel Decomposition below; this unit owns `static/*`
  and `tests/pwa/*` only.

Steps:
1. Tests red (pw harness): route-by-state, ask flow with SSE, offline, tweak.
2. `static/index.html` screens with spec copy; `manifest.webmanifest`,
   `sw.js`, placeholder box pictures.
3. Green on the mock backend; iPad viewport check; screenshots for review.
4. README "Try the PWA" section; PR into main; owner click-through on the Mac
   (deploy gate for this unit is the owner's review; Pi deploy comes with P1).

## Progress — P3
- [x] Step 1 — PWA tests written (red) — completed 2026-10-30 (P3 agent)
- [x] Step 2 — screens, manifest, service worker, placeholders — completed 2026-10-30 (P3 agent)
- [x] Step 3 — green on the mock backend (19 pw tests, 3 browsers), iPad viewport, screenshots in tests/pwa/screenshots — completed 2026-10-30 (P3 agent, PR #4)
- [x] Step 4 — README paragraph merged with PR #5, PR #4 merged 2026-10-30; owner click-through pending on the Mac

## Parallel Decomposition (P1 ∥ P3)

### Work Units

| Unit | Agent | Files Owned | Shared Files Owned | Depends On |
|------|-------|-------------|-------------------|------------|
| A — P1 flash core | main session | `hacklab/store.py`, `hacklab/board.py`, `hacklab/flash.py`, `hacklab/jobs.py`, `hacklab/app.py`, `tests/test_store.py`, `tests/test_board.py`, `tests/test_flash.py`, `tests/test_real_runner.py`, `tests/test_api.py`, `scripts/hil-flash.sh`, `provisioning/*`, `Dockerfile.dev` | `STRATEGY.md`, `README.md`, `hacklab/app.py` (adds the `/static` mount + `/` route) | — |
| B — P3 PWA | fork agent, worktree `feat/p3-pwa` | `static/*`, `tests/pwa/*` | — | assumes `/static` is mounted at `/static` and `/` serves `static/index.html` (Unit A adds it; until merged the agent serves via its own uvicorn `--app-dir` shim in tests only) |

### Shared File Registry

| File | Owner | Other units assume |
|------|-------|--------------------|
| `hacklab/app.py` | Unit A | Static mount exists after merge |
| `STRATEGY.md` | Unit A (main session) | Unit B reports progress in its PR body; main session ticks P3 boxes |
| `README.md` | Unit A | Unit B hands a "Try the PWA" paragraph in its PR body; main session pastes it |
| `pyproject.toml` | Unit A | Unit B adds no dependencies |

### Merge Order

1. Unit A (P1) merges first — it owns the shared files.
2. Unit B (P3) rebases onto main, then merges.
3. Serial final pass (main session): README paragraph, STRATEGY P3 ticks, run the full suite + pw tests on main.

## P1 plan — Flash core (2026-10-30, approved)

Goal: compile + flash a sketch folder to the attached Nano-class box from the
Pi, with port detection, bootloader auto-detect (remembered per box),
re-enumeration check and a persistent per-box version store with Undo and
Reset-to-baseline. Real runner behind the existing `JobRunner` protocol,
selected by `FAKE_BOARD`. Unit tests on `FakeBoard`; one HIL smoke script run
on the Pi with the **Omnibot Forklift** (the turret is not at hand; owner's
choice 2026-10-30: hardware on the Pi, auto-detect bootloader, persist
versions now). Verified in the Hack Pack IDE 2026-10-30: the Forklift is a
classic `StockCode.ino` + `config.h` sketch (not PlatformIO), Serial 115200,
uses pins 14-19 as digital inputs = A0-A5 on an ATmega328 Nano -> Nano-class,
same flash path as the turret. Hacks: AdvancedSwagDrive, Gyro. Its stock
sketch is the HIL payload (flashing it restores normal behaviour). Unlike the
turret's, the Forklift stock code carries NO license header, so it stays
user-supplied and untracked (`_to_delete/omnibot-stock/`, git-ignored) until
CrunchLabs' terms are checked. Its `config.h` uses the same `///{...}` Level 2
markers (`{"min":0,"max":255}`, `{"options":["true","false"]}`) -- note the
`options` form for P2's Tweak parser.

Decisions:
- `arduino-cli` is driven as a subprocess with `--json`; no Python Arduino
  library. One wrapper class, one command per method (board list, compile,
  upload). Toolchain lives under `/opt/hacklab` (install-toolchain.sh default
  PREFIX fixed from the stale `/opt/turret-lab`; Dockerfile.dev follows).
- A sketch is a directory (multi-file boxes), never a lone string; the API's
  `source` string becomes `<box>.ino` in a temp sketch dir.
- Board detection: `board list --json`, take the first serial port whose
  matching boards include `arduino:avr:nano` or whose VID:PID is a known
  Nano clone (CH340 1a86:7523, FTDI 0403:6001, 2341:0043); none -> job fails
  with the "is it plugged in?" kid message, no state change.
- Bootloader: upload with `cpu=atmega328` (new) first; on failure retry with
  `cpu=atmega328old`; the working value is cached in
  `data/<box>/board.json` and tried first next time. Verified on the Omnibot
  Forklift 2026-10-30: CH340 clone (1a86:7523, no USB serial number,
  `matching_boards` empty), NEW bootloader worked first try: compile 7838 B
  text / 491 B data, `upload --verify` 10.6 s, sketch banner `OMNIB V0.9.1`
  on serial at 115200 afterwards.
- Verification after upload: a CH340 is a separate chip, so the port never
  disappears on MCU reset (present 0.13 s after upload). "Re-enumeration"
  therefore = `upload --verify` succeeded AND the same port address is still
  listed within 10 s; a native-USB board (none on hand) would re-enumerate
  and is matched by serial number when present, else address. Failure ->
  "the box did not wake up" message and Reset is offered.
- Version store `data/<box>/versions/<NNNN>/` (sketch dir copy +
  `meta.json`: created, kind, parent, sha256, note). `baseline` = version
  0000, written on first use from the box's stock sketch; `current` symlink.
  Undo = flash previous, pop; Reset = flash 0000, drop everything after it.
  App state moves from the in-memory `versions` dict to the store.
- Compile and upload run in a worker thread (`asyncio.to_thread`) so SSE keeps
  streaming; one job at a time (global lock -- `ponytail:` one box, one USB).
- The runner emits the same stages/messages as `FakeJobRunner`; `log_ref`
  points at `data/<box>/logs/<job>.log` with full compiler/avrdude output.
- Parallelism: store (`store.py`) and board/flasher (`board.py`,
  `flash.py`) are file-disjoint but ~1 h each; serialized, merge overhead
  exceeds the saving. Runner + app wiring depend on both.

Verified live 2026-10-30: `arduino-cli` 1.5 flags `board list --json
--discovery-timeout`, `compile --fqbn --output-dir --json`, `upload --fqbn
--port --input-dir --verify --json`, `--board-options`. Captured from the Pi's own
install (arduino-cli 1.5.1, arduino:avr 1.8.8): `board details -b
arduino:avr:nano --json` -> `config_options[cpu].values` = `atmega328`
(ATmega328P), `atmega328old` (Old Bootloader), `atmega168`; so the fqbn is
`arduino:avr:nano:cpu=atmega328` / `...:cpu=atmega328old`. `board list --json`
-> `{"detected_ports": [...]}` (each: `port.address`, `port.protocol`,
`port.properties.{vid,pid,serialNumber}`, `matching_boards[].fqbn`). `compile
--json` -> keys `success`, `compiler_out`, `compiler_err`,
`builder_result.{build_path, executable_sections_size[{name,size,max_size}],
used_libraries}`; `--output-dir` yields `<sketch>.ino.hex` (+ .elf, .eep,
.with_bootloader.hex). Smoke sketch: text 1868/30720, data 328/2048.

Steps:
1. Toolchain on the Pi (`install-toolchain.sh` PREFIX=/opt/hacklab from a
   clone at `/opt/hacklab/src`); record arduino-cli JSON shapes + Nano
   options; fix the stale `/opt/turret-lab` defaults in install-toolchain.sh
   and Dockerfile.dev. (no app code)
2. Tests red: `tests/test_store.py` (save/current/undo/reset persist across
   instances, baseline pinned, multi-file dirs), `tests/test_board.py`
   (`ArduinoCli` parsing of recorded JSON via an injected runner; `FakeBoard`
   scripted failures), `tests/test_flash.py` (port missing, bootloader
   fallback + cache, re-enumeration timeout, happy path),
   `tests/test_real_runner.py` (stages, failure -> log_ref, undo/reset
   payloads), app tests for `FAKE_BOARD=0` wiring with `FakeBoard`.
3. `hacklab/store.py`, `hacklab/board.py` (ArduinoCli, FakeBoard, Port),
   `hacklab/flash.py` (Flasher), `RealJobRunner` in `jobs.py`; green, ruff.
4. App wiring: runner chosen by `cfg.fake_board`; `board_connected` from
   detection; versions from the store; `log_ref` served read-only to the
   maintainer (not the kid). Green.
5. HIL on the Pi: `scripts/hil-flash.sh` (compile + flash the stock-shaped
   mock sketch, undo, reset; prints bootloader used and re-enumeration time)
   run with the turret attached; record results. This is the deploy gate.
6. README (flash core, HIL), P1 notes, hygiene, PR, merge.

## Progress — P1
- [x] Step 1 — toolchain on the Pi (/opt/hacklab), JSON shapes + Forklift bootloader recorded, stale prefix fixed — completed 2026-10-30
- [x] Step 2 — tests written (red) — completed 2026-10-30
- [x] Step 3 — store, board, flash, RealJobRunner green — completed 2026-10-30
- [x] Step 4 — app wiring behind FAKE_BOARD green (static mount + / placeholder included for P3) — completed 2026-10-30
- [x] Step 5 — HIL smoke on the Pi with the Omnibot Forklift: flash/undo/flash/reset all done, ~36 s per turn — completed 2026-10-30
- [ ] Step 6 — README/notes, PR merged

## P5a — Remote access + device provisioning (plan, 2026-10-30)

Pulled forward from P5 on request: the Pi must be reachable and updatable
over the internet before the app exists. Scope: Tailscale SSH (break-glass,
root) + AWS IoT Core thing/cert + a report-only ops agent (shadow heartbeat).
Deferred to P5 proper: Jobs allowlist, minisign, S3 releases, deploy/rollback
scripts, read-only rootfs. Until then "update" = ssh over Tailscale + apt/git.

Verified 2026-10-30 (live): Pi 3 Model B, Pi OS trixie, Python 3.13.5;
Tailscale 1.104.4 has a trixie apt repo; Tailscale SSH works on the free
Personal plan and the default policy lets the owner ssh as root to their
own devices (check mode); `awscrt` 0.38.0 ships cp313-abi3 manylinux
aarch64 wheels so `awsiotsdk` installs on the Pi without a compiler.
IoT Core: 12-month free tier (2.25 M connection-min, 500 k messages,
225 k shadow ops); after that, Ireland prices $0.08/M connection-min,
$1/M messages, $1.25/M shadow ops -> one device at a 5-min heartbeat is
under $0.10/month. Account: Busyweb (`busyweb-sso`). IoT Core is NOT offered in af-south-1
(verified: no endpoint); all IoT resources go in **eu-west-1** (Ireland).
Tailscale has no email/password signup; the tailnet is created the first
time the owner signs in (Google/GitHub/Microsoft/Apple) at the login URL
that `tailscale up` prints.

Parallelism: two file-disjoint units (provision-device.sh vs ops agent +
tests) but each is ~1 h; serialized -- merge overhead exceeds the saving.

Decisions: agent uses `awsiotsdk` MQTT over mTLS (port 8883), classic
shadow of the thing; thing name `hacklab-<device>`; IoT policy scoped to
`${iot:Connection.Thing.ThingName}` so a leaked cert reaches only its own
topics; certs live in `/opt/hacklab/data/iot/` mode 0600, never in git
(`provisioning/local/` + `*.pem` already ignored). Agent is report-only:
no subscriptions that execute anything. Separate venv + unit
(`hacklab-ops.service`) per the architecture section.

Steps:
1. Tailscale on the Pi: apt repo + install, `tailscale up --ssh
   --hostname hacklab`; owner signs in at the URL (creates the tailnet);
   Mac client via `brew install --cask tailscale-app`; disable key expiry
   for the Pi in the admin console. Verify `ssh root@hacklab` from the Mac
   over the tailnet, and `tailscale status` on both.
2. Tests first: `tests/test_ops_agent.py` -- state collector (hostname,
   uptime, disk, CPU temp, wlan SSID/IP, comitup state, current release)
   with subprocess/`/proc` mocked; shadow payload shape; heartbeat loop
   tick with a fake MQTT client. (red)
3. `ops/agent.py` + `ops/pyproject`-less requirements (`awsiotsdk` pinned):
   connect, publish `$aws/things/<thing>/shadow/update` every 300 s with
   `reported` state, reconnect on drop. (green, ruff clean)
4. AWS via CloudFormation only (owner's rule, 2026-10-30): template
   `provisioning/iot-device.yaml` -- `AWS::IoT::Thing`, `AWS::IoT::Policy`
   (scoped to the thing), `AWS::IoT::Certificate` from a CSR parameter
   (status ACTIVE), `AWS::IoT::PolicyPrincipalAttachment`,
   `AWS::IoT::ThingPrincipalAttachment`; outputs cert id + ARN.
   `scripts/provision-device.sh <device>`: generates the EC key + CSR with
   openssl in `provisioning/local/<device>/` (private key never leaves the
   Mac), `aws cloudformation deploy` stack `hacklab-device-<device>` in
   eu-west-1, then fetches the cert PEM, ATS endpoint and Amazon Root CA 1
   into the same folder. Re-running = stack update, idempotent.
   `scripts/status.sh <device>` reads the shadow (table above). cfn-lint +
   shellcheck clean.
5. `provisioning/install-ops.sh` (run on the Pi over Tailscale; idempotent):
   `/opt/hacklab/ops` venv, copy certs to `/opt/hacklab/data/iot/`, write +
   enable `hacklab-ops.service` (Restart=always, After=network-online).
   Verify on the device: unit active, `status.sh hacklab-pi3` shows a fresh
   heartbeat; pull the Pi's power, confirm the heartbeat resumes.
6. README ops section; P5 notes; hygiene check (no account id, tailnet
   name, cert ids, network names in the diff); PR; merge.
   Deploy gate: this IS the deploy -- evidence = shadow heartbeat + ssh
   over Tailscale from the Mac.

## Progress — P5a
- [x] Step 1 — Tailscale SSH on the Pi and the Mac, `ssh root@hacklab` verified over the tailnet — completed 2026-10-30
- [x] Step 2 — ops agent tests written (red) — completed 2026-10-30
- [x] Step 3 — ops/agent.py green, ruff clean — completed 2026-10-30
- [x] Step 4 — iot-device.yaml CloudFormation stack + provision-device.sh + status.sh, lint clean, thing provisioned — completed 2026-10-30
- [x] Step 5 — install-ops.sh run end-to-end over Tailscale (root@hacklab), heartbeat in the shadow incl. tailscale_ip, survives reboot — completed 2026-10-30
- [ ] Step 6 — README/P5 notes, hygiene check, PR merged

## P5c notes — signed updates, verified 2026-10-30

- Chain verified end to end on the Pi: `release.sh` -> S3 -> `deploy.sh`
  (IoT Job) -> agent downloads with role credentials from the IoT credentials
  provider, verifies the minisign signature, `sudo hacklab-apply deploy` ->
  extract, `pip install -e`, switch `current`, restart, 60 s health check.
  0.1.1 and 0.1.2 SUCCEEDED (app serving from `releases/<v>`); `rollback.sh`
  back to 0.1.1; `logs.sh` fetched a bundle (job logs, asks.jsonl, spend);
  deploying 0.1.0 over 0.1.1 refused by the downgrade guard; `{"op":
  "shell"}` ended FAILED "rejected: unknown op".
- The very first deploy (0.1.0) was the best test: the tarball built on
  macOS carried 114 AppleDouble `._*` files, the profile loader choked on
  `._dance.toml`, the app failed its health check and the helper rolled back
  to the previous code inside the same job, reporting FAILED with the reason.
  Fixes: `COPYFILE_DISABLE=1 tar --no-xattrs` in `release.sh`, dotfiles
  ignored by the loader, `--warning=no-unknown-keyword` on extract.
- Things the live run found in the agent: modules not shipped by the
  installer; the SDK asserts a `QoS` enum; a device may not report
  `REJECTED` (the update was refused and the job looped) -> rejected ops end
  FAILED with "rejected: ..." and a job id is never run twice; `JobStatus`
  values are plain strings; the log bundle must be built in a temp dir
  (the data dir belongs to the app user). The shadow's `release` may show a
  failed version for one heartbeat during a rollback.
- Key custody ended up: unencrypted minisign key on the Mac, backed up
  (encrypted at rest by SSM, not by a passphrase) to
  `/hacklab/minisign/secret-key`; AWS SSO + MFA is the single root of trust
  for both jobs and signing. Recorded as the owner's decision.
- Working from another machine: clone, `aws sso login --profile busyweb-sso`,
  `scripts/device-secrets.sh restore pi3`, `restore-key`,
  `restore-signing-key`, install `minisign` + `awscli`; then `release.sh` /
  `deploy.sh` / `rollback.sh` / `logs.sh` / `status.sh` work. Nothing is
  tied to this Mac.

## Remote-UI notes, verified 2026-10-30

- Policy lives in `hacklab/remote.py` (classification + helping switch) and
  one `writable(request)` guard in the API. Verified from the Mac: over
  Tailscale `source=remote`, writes 403 until helping; from the LAN the
  switch itself is 403; with helping on, a real ask over Tailscale compiled
  and flashed the Forklift (57 s) and the LAN status showed `helping=true`;
  off again -> 403. `asks.jsonl` carries `"source": "tailscale"`,
  `data/helping.jsonl` the peer address of every flip.
- Browser suite reworked (owner's ask): the mock-only tests had drifted since
  P2 (mock data gone) and passed only by test order. Now: `tests/pwa/pwa.spec.js`
  (mock backend: screens, SSE stages, failure path, offline, tweak clamp,
  remote view, helping, ?admin=1, busy Let's go) and `tests/pwa/fullstack.spec.js`
  (real runner + store + profiles + templates + skeleton on the emulated
  board, `HACKLAB_GENIE=golden` replays the recorded answers by request):
  ask -> assembled real code on Done -> Undo; a shipped trick becomes a
  version; a tweak renders the chosen number into the stored sketch; Reset
  truncates to 0000. 43 tests on Chromium, Firefox and WebKit. Only the USB
  cable is outside the browser suite (`scripts/hil-*.sh` on the Pi).
- Two real bugs the suite found: a late job sync overwrote the Done
  heading with the compiling text (Firefox timing); and the unresponsive
  "Let's go" the owner reported (status blocked ~10 s on detection; now
  stale-while-revalidate plus a busy state on the button).
- Not in CI: the browser suite runs through the machine-wide `pw` harness on
  the Mac; GitHub CI runs pytest and the compile matrix only.

## P5b notes — appliance, verified 2026-10-30

- `install.sh` ran three times on the Pi (first two aborted on real bugs,
  third clean): `/etc/default/hacklab` is now merged variable by variable so
  a pushed key survives re-runs; `config.toml` is git-ignored by pattern, so
  the appliance config is `provisioning/appliance.toml`.
- Hardening found two silent failures: (1) arduino-cli's build cache defaults
  to `~/.cache` and the service home is read-only under `ProtectSystem=
  strict` -> `build_cache.path` under `/opt/hacklab/arduino/cache` in the
  generated `arduino-cli.yaml`; (2) arduino-cli reports that kind of failure
  in a top-level `error` field with empty `compiler_err` -> now in the log.
- `/api/status` cost 10 s per call (one `board list` each; the PWA polls it)
  -> detection cached 10 s (`DETECT_TTL`), flash still looks fresh. Under
  load the 2 s discovery window missed the board once -> 5 s.
- A 409 on box select used to leave the box half-selected and the next
  `/api/sketch/current` crashed (seen from the PWA) -> select only after the
  baseline exists.
- The service ignored SIGTERM while a worker thread compiled (90 s then
  SIGKILL) -> `TimeoutStopSec=20`, `KillMode=mixed`.
- comitup `web_service: hacklab-app.service` set; the unit stays disabled in
  systemctl so comitup owns it (hotspot takes :80, home WiFi gives it back).
- Observed from the Mac: PWA loads at `http://hacklab.local/`, ask through
  the service done in 56 s, Undo 46 s. The owner opened the PWA from the Mac
  during the install (requests visible in the journal).
- Hand-off verified (journal): `comitup-web` started and `hacklab-app`
  stopped when the hotspot came up; the phone's portal probes were served;
  after the portal connect `comitup-web` stopped and `hacklab-app` started
  (59 s from rejoin to the app answering on :80 from the Mac).
- Remote UI over Tailscale works already: `http://hacklab/` (MagicDNS, port
  80 on all interfaces) serves the PWA and API from the Mac; the PWA uses
  relative URLs only. The owner's read-only-by-default / admin-toggle /
  "helping" banner / source=tailscale logging requirements (notes above) are
  the next plan step, not yet built.
- Device-only content on this Pi: `/opt/hacklab/data/boxes/omnibot-forklift/
  {stock/StockCode, genie/skeleton.ino}` (owner-supplied, not in git).

## P4 notes — the AI helper, verified 2026-10-30

- Live on the Pi with the Forklift (`scripts/hil-ask.sh`): "lift the fork up
  for one second then put it down, every five seconds" -> one call (79 in /
  1117 out, 9384 cached), a millis()-based loop rule with two tweakables and
  kid labels, compiled and flashed first try, Undo back to stock. Turn 51 s
  of which compile+flash ~36 s. Cost $0.013. Goldens for the turret recorded
  live: both sketches compile; impossible ("make it fly") and off-mission
  (homework) asks come back as `explain` in kid language.
- Two things the HIL found: (1) multi-file boxes need the stock sketch's
  sibling files (`config.h`) copied next to the genie sketch -- taken from
  the baseline version now; (2) the `anthropic` import takes ~15 s on a Pi 3
  and app start ~18 s (hil scripts wait 60 s; the P5 service starts once).
- Retry path exercised for real: three failed compiles end as `failed` with
  the kid message and the full compiler log in the job log.
- Persona tweak after the run: the model said "press upload" -- the app
  flashes by itself, so the rules now forbid mentioning upload/app buttons.
- Spend: `data/spend/YYYY-MM.jsonl`, price table in `hacklab/spend.py`
  (Sonnet 5.5 $2/$10 per MTok, cache read $0.20); cap from `monthly_cap_usd`;
  the Console workspace limit is the second, independent cap.
- Key handling: `.env` on the Mac (git-ignored, backed up to Parameter Store
  `/hacklab/anthropic/api-key`); on the Pi passed per run for now, root-only
  `/etc/default/hacklab` when P5's install.sh creates the service.
- Forklift skeleton lives only on the device (`/root/hil/forklift-skeleton.ino`
  for HIL; `data/boxes/omnibot-forklift/genie/skeleton.ino` in production).

## P2 notes — box profiles, verified 2026-10-30

- Profiles are TOML (stdlib). `scripts/check-box.sh ir-turret` on the Pi: 7
  behaviours + 2 templates + 2 stock sketches compile for arduino:avr:nano
  in ~3 min (11 x ~17 s). CI runs the same compile tests inside the dev
  container (`HACKLAB_CLI` set in the docker step).
- Tweak markers: the IDE's `///{...}` convention plus our `"label"` key for
  kid-facing slider text; the stock `yawStopSpeed` marker is stripped from
  derived sketches ("keep this at 90"). Behaviour-specific numbers are placed
  above the stock params so they come first in the Tweak screen.
- Behaviours are generated from the stock sketch by text insertion (switch
  cases, params, functions, loop prelude) -- the generator was a one-off and
  is not committed; the sketches are. Each file keeps the MIT header.
- Omnibot Forklift profile uses `stock.location = "device"`; the stock code
  must be copied to `data/boxes/omnibot-forklift/stock/StockCode/` on the Pi
  (no license header, not in git). The HIL script seeds it from
  `/root/hil/StockCode`. Roulette hack for the turret still to fetch from
  the IDE (it never loaded as an editor model).
- API gaps the P3 agent listed, now partly closed: per-tweakable label (done);
  still open: job cancel, version title + timestamp in `/api/status`,
  per-stage explanation text, per-value "what it will do" summary, PNG box
  pictures (SVG placeholders in use).

## P1 notes — flash core, verified on the Pi 2026-10-30

- HIL (`scripts/hil-flash.sh omnibot-forklift /root/hil/StockCode`, real app
  via HTTP, FAKE_BOARD=0): select box -> flash serial sketch (36 s, banner
  `hacklab hil`) -> undo (36 s, banner `OMNIB V0.9.1`) -> flash (35 s) ->
  reset (36 s, stock banner). Versions back to `0000` only. Bootloader cache
  `{"cpu": "atmega328"}` (new bootloader; no fallback needed).
- Turn anatomy on a Pi 3: `arduino-cli board list` ~10 s (Go binary + serial
  discovery, even with `--discovery-timeout 2s`), compile ~9 s, upload with
  verify ~8 s, verification `board list` ~10 s. Detection is 20 of the 36 s.
  ponytail: replace both `board list` calls with a pyserial/`/dev/serial/by-id`
  scan if turns need to get shorter; keep `board list` for the first detect.
- Bugs the real board found that FakeBoard had let through: arduino-cli
  requires `<dir>/<dir>.ino`; temp dirs, store versions and the mock baseline
  all violated it. FakeBoard now enforces the rule. One job failed once with
  an empty port list right after a successful status detect (not reproduced;
  the job log now records the raw port list and any CLI exception).
- Internal exceptions in a job now end it as `failed` with the error in its
  log instead of leaving the job in `queued` forever.
- Forklift stock sketch lives only in `_to_delete/omnibot-stock/` (no license
  header) and on the Pi at `/root/hil/StockCode`.

## P5 notes — WiFi fallback (comitup), verified 2026-10-27

- `sudo apt install comitup` (one binary package, v1.43; `comitup-watch` is
  not in Debian and not needed).
- `/etc/comitup.conf`: `ap_name: hacklab-setup`, `ap_password: <sticker>`,
  `enable_appliance_mode: true`.
- DO NOT mask `wpa_supplicant` on NetworkManager-based OS (NM drives it; masking
  leaves `wlan0 unavailable` + DBusException in comitup). `systemd-resolved`
  does not exist on Raspberry Pi OS; skip. Masking `dnsmasq` is fine.
- Remove home WiFi profile to exercise the hotspot: `nmcli con delete <name>`.
- Status: `comitup-cli i`, `nmcli dev status`, `rfkill list`, `nmcli radio wifi`;
  regdomain fix `sudo raspi-config nonint do_wifi_country ZA`.
- 2026-10-30 device renamed turret -> hacklab (`hostnamectl set-hostname`,
  /etc/hosts 127.0.1.1 line, `ap_name: hacklab-setup`, stale
  `turret-setup-0000` NM profile deleted, avahi + comitup restarted).
  comitup-cli reports `Host hacklab-setup.local`; hostname survived a power
  cycle.
- 2026-10-30 clean-power fallback test: home WiFi profile deleted, reboot.
  ~25 s after boot wlan0 is `type AP ssid hacklab-setup` (channel 11),
  comitup `HOTSPOT state`, dnsmasq serving 10.41.0.100-150 on 10.41.0.1.
  iPhone joined (DHCPACK 10.41.0.113), iOS probed `/hotspot-detect.html`
  (comitup-web 302) and fetched the portal page + assets within 2 s of the
  lease: captive-portal sheet opened automatically, no browse-to-address.
  Switchover: picked the home SSID in the portal, `POST /connect`; ~20 s
  later wlan0 is `type managed` on the home WiFi with its old DHCP address,
  comitup `CONNECTED state`, `hacklab-setup-0000` profile kept (inactive)
  for the next fallback. Whole loop verified headless over the wired link.
- 2026-10-30 `hacklab.local` only resolves when the client is on the SAME
  WiFi network as the Pi. From the dev Mac on a different Deco SSID (same
  /24, unicast ssh to the IP fine) it never resolved: raw multicast tests
  showed Mac -> Pi mDNS arrives, Pi -> Mac on other groups arrives, but
  Pi -> Mac on 224.0.0.251 is dropped (the Deco does not forward the mDNS
  group across its networks). Once the Mac was on the Pi's SSID:
  `ssh admin@hacklab.local uptime` works, resolving to wlan0's address.
  Pi side is clean (avahi announces on eth0 + wlan0, no firewall, rp_filter
  loose). Setup instructions for the iPad must say "join the same WiFi
  network as the box"; guest networks and multi-SSID routers will break
  `http://hacklab.local`, so keep an IP / QR-code fallback in mind.
- 2026-10-30 hotspot would not start (Pi OS trixie, kernel 6.18.50+rpt,
  NM 1.52.1, wpasupplicant 2:2.10-24+rpt3, BCM43430 brcmfmac). Symptom: NM
  "Hotspot network creation took too long ... supplicant-timeout" every ~25 s.
  Root cause (from `journalctl -u wpa_supplicant -b`): "nl80211: kernel reports:
  key setting validation failed" -> "Could not connect to kernel driver" ->
  "Failed to initialize AP interface". NM 1.52 enables PMF (802.11w) on the AP
  and brcmfmac has no BIP cipher (only WEP/TKIP/CCMP-128), so the kernel
  rejects the management key. Confirmed: bare `nmcli dev wifi hotspot` fails
  identically; `wifi-sec.pmf disable` on the same profile -> AP-ENABLED in <2 s.
  Channel/band and regdomain were red herrings (channel 6 patch to comitup's
  nm.py tried and reverted; file restored from nm.py.orig, which is still
  there).
- Fix (survives comitup upgrades): `/etc/NetworkManager/conf.d/10-wifi-no-pmf.conf`
  containing `[connection]` / `wifi-sec.pmf=1` (1 = disable; documented default
  key in `man NetworkManager.conf`). `systemctl reload NetworkManager`, delete
  the stale `hacklab-setup-0000` profile, `systemctl restart comitup`. Verified:
  `nmcli dev status` wlan0 connected on hacklab-setup-0000, `iw dev wlan0 info`
  type AP ssid hacklab-setup, dnsmasq serving 10.41.0.100-150. Applies to STA
  profiles too (PMF off for home WiFi) -- fine, this chip has no WPA3 anyway.
  install.sh must ship this file.
- Device secrets backup (2026-10-30): the per-device cert, private key, CSR,
  endpoint and root CA (2.7 KB total) are stored as SecureString parameters
  under `/hacklab/devices/<device>/` in Parameter Store, eu-west-1, default
  SSM KMS key, standard tier (free, 4 KB limit each). `scripts/device-secrets.sh
  restore pi3` recreates `provisioning/local/pi3/` byte for byte (verified);
  `provision-device.sh` backs up automatically. Not CloudFormation on purpose:
  secret values must not live in a template or stack parameter.
- Also noted: `iw`, `rfkill`, `comitup-cli` live in /usr/sbin (need sudo or
  full path); comitup names a bare-nmcli test profile "Hotspot" -- delete it.

## P5 notes — remote ops (P5a), verified 2026-10-30

- IoT Core has no af-south-1 endpoint; everything lives in eu-west-1 under
  CloudFormation stack `hacklab-device-<device>` (`provisioning/iot-device.yaml`).
  Cert issued from a local P-256 CSR, valid to 2049, ACTIVE, attached to the
  thing and to a policy scoped to `client/hacklab-<device>` and that thing's
  shadow + `hacklab/<device>/*` topics.
- Agent (`ops/agent.py`, awsiotsdk 1.31.0 in `/opt/hacklab/ops/venv`, runs as
  system user `hacklab-ops`, certs 0600 in `/opt/hacklab/data/iot/`) connects
  in ~3 s on a Pi 3 and reports every 300 s. A `None` field is dropped from
  the shadow (IoT treats null as delete) -- `tailscale_ip` appears only once
  the node is logged in. Verified: `scripts/status.sh pi3` shows a fresh
  heartbeat before and after a reboot (agent up 47 s after boot).
- Tailscale 1.104.4 installed from its trixie repo; `tailscale up --ssh
  --hostname hacklab` leaves the node waiting at a login URL until the owner
  signs in (that first sign-in creates the tailnet). Mac client is a cask
  that needs the Mac admin password (`brew install --cask tailscale-app`).
- Tailscale verified: Pi node `hacklab` online, `ssh root@hacklab` from the
  Mac works with no key setup (Tailscale SSH, owner's default policy),
  `install-ops.sh pi3 root@hacklab` re-ran idempotently and the shadow now
  carries `tailscale_ip`. Gotcha: do not reboot the Pi while a `tailscale up`
  login is pending -- the owner's sign-in then registers a node the restarted
  daemon knows nothing about (stale offline entry, Pi still "Logged out");
  re-run `tailscale up` for a fresh URL. Node key expiry disabled in the
  admin console 2026-10-30 (required for a headless device).
- Gotcha: `printf pw | sudo -S tee FILE` feeds the password to tee, not the
  piped content -- write files with `sudo -S bash -c 'curl ... -o FILE'`.
  Both affected files were rewritten before anything was installed.

## P5 notes — remote use of the UI over Tailscale

- The maintainer reaches the same UI the nephew uses: `http://hacklab:<port>`
  via MagicDNS, or `tailscale serve --bg <port>` for a tailnet-only HTTPS name.
  `hacklab.local` never works remotely (mDNS is link-local), so the PWA and
  API use **relative URLs only** — never a hard-coded hostname.
- Requests arriving from the Tailscale interface (100.64.0.0/10) are
  **read-only by default**: the UI shows status, current sketch, log tail,
  and the box picker, but flash/undo/reset buttons are disabled with a clear
  "remote view" banner.
- **Remote flashing is allowed on purpose** — the maintainer may need to fix
  things or do what the nephew asks for over the phone. Enable it per session
  with an explicit `?admin=1` (or an "I'm here to help" toggle); while it is
  on, the kid-facing screen shows "Uncle is helping" so a flash from afar is
  never a surprise, and every remote action is logged with source=tailscale.
- Never expose the admin toggle on the LAN side; it is gated on the source
  interface, not on a password.

## P5 notes — security

- Setup hotspot WPA2 + sticker passphrase; portal is HTTP but only over that
  encrypted link and only while no known network exists.
- WiFi password only in NM's root-only connection file [VERIFY mode 600];
  backend runs unprivileged, hands credentials to NM via nmcli/D-Bus; never
  logged.
- Remote ops: X.509 per-device cert, mutual TLS to IoT Core; Jobs payloads
  signed; agent executes only an allowlist (apply update, restart unit, upload
  log bundle, report state). SSH via Tailscale only, key auth, root allowed.
- Anthropic key: root-only env file, dedicated key, spend cap, revocable.
- Accepted: SD card readable by anyone with physical access.

## Public-repo hygiene

- `.gitignore`: `.env`, `config.toml`, `secrets/`, `provisioning/local/`,
  sketch version store, logs, IoT certs.
- No PII: nephew's name, network names, Tailscale/IoT identifiers in untracked
  config only.
- API key via env only; CI never touches real keys.

## UI backlog (owner, 2026-10-30; postponed, not yet planned)

- **Per-box suggestions and copy.** "Try one of these" is empty for the
  Omnibot Forklift (no behaviours shipped for it) and the ask placeholder
  "Make it shake its head when I press 7" is turret copy. Both must come from
  the box profile: `profile.toml [copy]` with `ask_placeholder` and
  `suggestions` (ids of behaviours, or plain asks for boxes without a
  behaviour library), served through `/api/boxes` / `/api/status`; the PWA
  invents nothing. Forklift behaviours themselves are blocked on the stock
  code's license (device-only), so its suggestions are asks.
- **Code view with developer comfort.** Syntax highlighting and
  autocompletion when viewing/editing the whole sketch (Level 3). Constraint:
  no external links or CDNs, works offline on the Pi -> a vendored editor
  (CodeMirror 6 with the C++ mode, built once into `static/vendor/`, MIT) and
  completions seeded from the box's helper list, pins and the stock sketch's
  identifiers. Keep the kid-facing default simple; the editor is Level 3.
- Carry over from the P3 agent: version title + timestamp on the Home card,
  per-stage explanation text, job cancel, PNG box pictures.

## Roadmap item — every Hack Pack box, zero maintenance on arrival (owner's ask 2026-10-30)

The owner is subscribed to the whole Hack Pack range: a new box must work
without a maintenance visit. Not MVP, but to be provisioned for ahead of time:

- **Content pipeline:** `scripts/import-box.sh <id>` pulls a box's stock code
  and hacks from the Hack Pack IDE (browser automation, same editor-model
  read used by hand on 2026-10-30), keeps MIT-headed files in `boxes/<id>/
  stock/`, else stages them for the device, scaffolds the profile from
  `boxes/_template`, derives pins/limits from the sketch's `#define`s and
  `///{}` markers, and runs `check-box.sh`. One command per new box.
- **Board registry:** newer boxes (Nixie Clock, Color Composer, Space
  Oddity, Robot Ranger, RoboLamp, Tank Plant, Omnibot Forklift's successors)
  are PlatformIO-style and some are ESP32-class. The profile's `[board]`
  already carries fqbn + core; `install-toolchain.sh` must pre-install every
  core the profiles reference (`arduino:avr`, `esp32:esp32`, ...) and the
  flasher must learn each core's upload quirks (ESP32: no bootloader cpu
  option, `esptool` resets, native-USB re-enumeration). The P1 `KNOWN_NANO`
  VID:PID list becomes a per-board table.
- **Skeleton per box** for the AI helper, generated by the same import script
  (markers after the params block, in `loop()`, before the first function).
- **CI matrix:** `check-box.sh` for every box on every push (already), plus
  the cores cached in the dev image so the matrix stays fast.
- **Delivery:** new box = one PR with content only, shipped by P5c's signed
  release; the Pi needs no login.
Owner's note: "I don't want to be forced to do maintenance when a new hack
pack arrives." Plan this as P6 (replacing the single Laser Synthesizer
profile with the general pipeline, Laser Synth as its first proof).

## Open decisions

1. Raw API loop vs Claude Agent SDK for P4: raw Messages API, one call per
   turn (closed 2026-10-30).
2. Laser Synthesizer: Nano-class per its pin usage (A6/A7); confirm by
   plugging it in and checking the USB chip/bootloader before P6.
3. AWS account for IoT Core: Busyweb (closed 2026-10-30).

## Testing policy

Every phase: tests for new/changed code, run, fix until green before the phase
is done. Hardware paths: mocked unit layer + manual HIL script in README. Every
shipped behaviour and template must compile in CI.

## Estimate

Original (turret-only) 25–40 h. Scope now adds profiles, offline path, ops
agent: judgment, not verified — 45–70 active hours; MVP cut (P0–P4 with
ir-turret only, P5 minimal) 25–35 h.

## P0 plan (2026-10-28, approved; done via PR #1)

Decisions taken with the maintainer on 2026-10-28: the mock backend is the
real FastAPI skeleton with a swappable fake job runner (nothing thrown away in
P1/P2); package name `hacklab`; MIT, copyright "Warrenn"; docs committed to
main before the P0 branch.

Verified 2026-10-28: arduino-cli latest is v1.5.1 (Linux_ARM64 asset exists;
install script pins with `sh -s 1.5.1`, `BINDIR` sets the target);
`debian:bookworm` and Pi OS Bookworm ship Python 3.11.2; GitHub-hosted
`ubuntu-24.04-arm` runners are GA and free for public repos; fastapi 0.162,
uvicorn 0.54, ruff 0.17, pytest 9.2 are current.

Parallelism: **serial, one agent.** Units (package, provisioning/Docker, CI)
are each under an hour, CI is only verifiable once the other two exist, and
all three touch pyproject.toml / README / .gitignore (3 shared files > budget).

Layout after P0:
```
LICENSE  README.md  config.example.toml  pyproject.toml  .gitignore
hacklab/        __init__.py  config.py  app.py  jobs.py  mock_data.py
tests/          test_config.py  test_api.py
provisioning/   install-toolchain.sh  libraries.txt
Dockerfile.dev  docker-compose.yml
.github/workflows/ci.yml
```

Design:
- `hacklab/config.py`: `tomllib` reads `config.toml` if present (example
  committed as `config.example.toml`); env overrides `FAKE_BOARD`,
  `HACKLAB_DATA_DIR`, `ANTHROPIC_API_KEY` (env only, never in the file).
- `hacklab/jobs.py`: `JobRunner` protocol (`submit(kind, payload) -> job_id`,
  `get(job_id)`, `subscribe()`), and `FakeJobRunner`: asyncio task walks
  queued→thinking→compiling→uploading→verifying→done with a per-stage delay
  (`HACKLAB_MOCK_DELAY`, default 1 s, 0 in tests) and a canned kid message per
  stage. P1 adds the real runner behind the same protocol.
- `hacklab/mock_data.py`: ir-turret + laser-synth box entries, 3 behaviours
  with `///{range}` tweakables, a stock-sketch excerpt (MIT header kept), 2
  concepts. Replaced by the profile loader in P2.
- `hacklab/app.py`: every route in the API contract; SSE on `/api/events` via
  `StreamingResponse` (no extra dependency). Flash/ask routes refuse (409) when
  no box is selected — the "never flash box A while the picker says B" rule
  lives here from day one.
- `provisioning/install-toolchain.sh`: idempotent; `PREFIX` (default
  `/opt/hacklab`); venv + `pip install -e .`; arduino-cli 1.5.1 into
  `$PREFIX/bin`; `ARDUINO_DIRECTORIES_*` under `$PREFIX/arduino`; `arduino:avr`
  core; libraries from `provisioning/libraries.txt` (IRremote pinned; exact
  version checked against `arduino-cli lib search` during this phase).
- `Dockerfile.dev`: `debian:bookworm`, runs the same script, then compiles a
  minimal sketch for `arduino:avr:nano` as the image's own smoke test — a
  broken toolchain fails the build. `docker-compose.yml`: bind-mount, :8000,
  `FAKE_BOARD=1`.
- CI: `test` job (ubuntu-latest, Python 3.11, ruff + pytest) and `toolchain`
  job (`ubuntu-24.04-arm`, `docker build -f Dockerfile.dev`).
- Skipped in P0: dependency lock file (pins land in `release.sh`, P5);
  static PWA mount (P3); FakeBoard serial emulation (P1).

Steps (tests before implementation):
1. Branch `feat/p0-scaffold`; LICENSE, README skeleton, .gitignore fix (stock
   sketches are now committed), `config.example.toml`, `pyproject.toml`.
2. Write `tests/test_config.py` and `tests/test_api.py` (red).
3. Implement `config.py`, `mock_data.py`, `jobs.py`, `app.py` until green;
   `ruff check` clean.
4. `provisioning/install-toolchain.sh` + `libraries.txt` (shellcheck clean);
   `Dockerfile.dev` + `docker-compose.yml`; local `docker build` passes the
   smoke compile; `docker compose up` answers `/api/status`.
5. `.github/workflows/ci.yml`; push; both jobs green.
6. README filled in (dev quickstart, test, layout, hygiene); PR; merge.
   Deploy gate: local-only until P5 — flagged "merged, not deployed".

## Progress — P0
- [x] Step 1 — branch, LICENSE, README skeleton, .gitignore, config example, pyproject — completed 2026-10-28
- [x] Step 2 — tests written (red) — completed 2026-10-28
- [x] Step 3 — config, mock data, fake runner, app (green, ruff clean) — completed 2026-10-28
- [x] Step 4 — install-toolchain.sh, Dockerfile.dev, compose; local docker build green — completed 2026-10-28
- [x] Step 5 — CI workflow green on both jobs — completed 2026-10-28
- [x] Step 6 — README complete, PR #1 opened and merged — completed 2026-10-28
