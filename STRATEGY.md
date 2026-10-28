# STRATEGY.md — Hack Lab (repo: turret-lab)

Kid-facing "program your robot" system for CrunchLabs Hack Pack boxes. An
11-year-old with only an iPad asks in plain language for a behaviour ("make it
shake its head when I press 7"); a headless Raspberry Pi 3 at his home turns
that into code, compiles it, flashes the box over USB, and reports back in kid
language. When the AI is unavailable he can still pick, tweak, and flash
behaviours himself. Public GitHub repository.

Design rationale (the *why*) lives in the Claude doc "Turret Lab Design
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
2. **iPad is his only device.** PWA at `http://turret.local`, no login, no
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
  hostname `turret`, user `admin`, keyboard us, SSH enabled.
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
/opt/turret-lab/
  releases/<version>/   immutable deployed versions
  current -> releases/… symlink the services run from
  venv/                 from install-toolchain.sh
  data/                 writable partition: sketch versions, logs, config.toml
systemd: turret-app.service, turret-ops.service (separate venv; app deploys
never restart it)
```
First install: clone + `provisioning/install.sh` (idempotent) on a visit or
over Tailscale. After that, no logins to deploy.

Release → signed job → agent:
1. CI on tag: `turret-lab-<version>.tar.gz` (app, profiles, PWA,
   `manifest.json` with sha256 per file), signed with **minisign** (private key
   in GitHub secrets, public key baked onto the Pi), uploaded to private S3.
2. Maintainer creates an IoT Job: `{op: deploy, version, url (presigned S3),
   sig}`.
3. Ops agent: download to `releases/<version>/`, verify signature + checksums,
   `install.sh --release`, swap `current`, restart `turret-app`, poll
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

Deferred (recorded, not scheduled): physical reset button; points/levels;
block-based editor; curated external links; conversational correction;
touchscreen kiosk page; Bluetooth onboarding (rejected — needs native app).

## P5 notes — WiFi fallback (comitup), verified 2026-10-27

- `sudo apt install comitup` (one binary package, v1.43; `comitup-watch` is
  not in Debian and not needed).
- `/etc/comitup.conf`: `ap_name: turret-setup`, `ap_password: <sticker>`,
  `enable_appliance_mode: true`.
- DO NOT mask `wpa_supplicant` on NetworkManager-based OS (NM drives it; masking
  leaves `wlan0 unavailable` + DBusException in comitup). `systemd-resolved`
  does not exist on Raspberry Pi OS; skip. Masking `dnsmasq` is fine.
- Remove home WiFi profile to exercise the hotspot: `nmcli con delete <name>`.
- Status: `comitup-cli i`, `nmcli dev status`, `rfkill list`, `nmcli radio wifi`;
  regdomain fix `sudo raspi-config nonint do_wifi_country ZA`.
- Still to test on clean power: hotspot visible on iPad; captive-portal
  auto-popup vs browse-to-address; switchover; fully headless run.

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

## Open decisions

1. Raw API loop vs Claude Agent SDK for P4 (raw loop is the low-risk default)
   [VERIFY SDK footprint on Pi 3 arm64].
2. Laser Synthesizer: Nano-class per its pin usage (A6/A7); confirm by
   plugging it in and checking the USB chip/bootloader before P6.
3. AWS account for IoT Core (Busyweb vs new).

## Testing policy

Every phase: tests for new/changed code, run, fix until green before the phase
is done. Hardware paths: mocked unit layer + manual HIL script in README. Every
shipped behaviour and template must compile in CI.

## Estimate

Original (turret-only) 25–40 h. Scope now adds profiles, offline path, ops
agent: judgment, not verified — 45–70 active hours; MVP cut (P0–P4 with
ir-turret only, P5 minimal) 25–35 h.
