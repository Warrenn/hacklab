# Hack Lab

Kid-facing "program your robot" lab for CrunchLabs Hack Pack boxes. An
11-year-old with an iPad asks for a behaviour in plain language; a headless
Raspberry Pi turns it into an Arduino sketch, compiles it, flashes the box over
USB and reports back in kid language. Without the AI helper the kid can still
pick, tweak and flash pre-tested behaviours.

- `STRATEGY.md`: what gets built, in what order, and the current phase plan.
- `docs/DESIGN.md`: why, including the decision log.
- `docs/screens/`: the visual spec for the iPad app.

## Status

P0 (repo scaffold, mock backend, Pi toolchain image, CI) is done. The backend
serves the full API with a fake job runner; nothing talks to a real board yet.

## Develop on a Mac

Everything the Pi runs, runs in an arm64 Debian container built from the same
`provisioning/install-toolchain.sh`.

```sh
docker compose up            # builds the image on first run (a few minutes)
curl localhost:8000/api/status
```

The repo is bind-mounted and uvicorn reloads on save. From an iPad on the same
WiFi, open `http://<mac-ip>:8000`.

Inside the container the Pi toolchain is on `PATH`:

```sh
docker compose exec app arduino-cli --config-file /opt/hacklab/arduino/arduino-cli.yaml board list
docker compose exec app pytest -q
```

Without Docker (tests and the mock backend only):

```sh
uv venv -p 3.11 .venv && uv pip install -p .venv/bin/python -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
FAKE_BOARD=1 .venv/bin/uvicorn hacklab.app:app --reload
```

## Try the mock API

```sh
curl -X POST localhost:8000/api/box -H 'content-type: application/json' -d '{"id":"ir-turret"}'
curl -X POST localhost:8000/api/flash/behaviour -H 'content-type: application/json' -d '{"id":"shake-no"}'
curl -N localhost:8000/api/events        # live job progress (SSE)
```

An ask whose text starts with "fail" exercises the failure path. Every route is
in the API contract in `STRATEGY.md`.

**Try the PWA.** With the mock backend running (`FAKE_BOARD=1 ANTHROPIC_API_KEY=dummy
uvicorn hacklab.app:app`), open `http://localhost:8000/` on a Mac or an iPad on the
same network. Unset `ANTHROPIC_API_KEY` to see the Offline screen. Browser tests:
`pw test "hacklab/tests/pwa/"` (machine-wide Playwright harness; the path filter keeps
agent worktrees under `.claude/worktrees` out of the run; set `HACKLAB_PYTHON` if the
venv is not at `.venv`). Screenshots of every screen are in `tests/pwa/screenshots/`.

## Configuration

Copy `config.example.toml` to `config.toml` (untracked). The Anthropic API key
is read from the `ANTHROPIC_API_KEY` environment variable only; a key in the
file is ignored. `FAKE_BOARD=1` and `HACKLAB_DATA_DIR` override the file.

## Layout

```
hacklab/          backend: config, app (API routes, SSE), jobs (runner protocol
                  + fake runner), mock_data (P0 fixtures)
tests/            pytest
provisioning/     install-toolchain.sh (Pi and Docker), libraries.txt (whitelist)
Dockerfile.dev    arm64 Bookworm dev stand-in for the Pi; its build compiles a
                  smoke sketch, so a broken toolchain fails the build
.github/          CI: ruff + pytest; image build on an arm64 runner
```

Coming per phase: `boxes/<id>/` profiles (P2), the PWA (P3), the AI helper
(P4), `provisioning/install.sh`, systemd units and `scripts/` for release,
deploy, rollback, status and logs (P5).

## Releases and remote updates (P5c)

AWS access for the scripts: `AWS_PROFILE` defaults to `busyweb-trusted` (an IAM
Roles Anywhere profile: certificate-based, no interactive login, so unattended
releases do not stall on an expired SSO token). From a machine without that
certificate, run with `AWS_PROFILE=busyweb-sso` after `aws sso login`.

```
scripts/release.sh 0.2.0          # git archive of HEAD + manifest, minisign-signed, uploaded to S3
scripts/deploy.sh pi3 0.2.0       # IoT Job; waits and prints SUCCEEDED/FAILED with the reason
scripts/rollback.sh pi3           # previous release on the device
scripts/logs.sh pi3               # log bundle from the device into provisioning/local/pi3/logs/
scripts/deploy.sh pi3 --op restart|report-state|apt-upgrade
```

On the Pi the ops agent (unprivileged) downloads the release with short-lived
role credentials obtained from its device certificate (IoT credentials
provider, role alias `hacklab-device`), verifies the signature against
`/opt/hacklab/minisign.pub`, then calls the only privileged command it is
allowed, `hacklab-apply`, which re-verifies, installs into
`/opt/hacklab/releases/<version>`, switches `current`, restarts the app and
rolls back automatically if the app is not healthy within 60 s. Downgrades are
refused (use rollback). Jobs with any other operation are rejected; no job
content is ever executed. Infrastructure: `provisioning/releases.yaml`
(bucket, device role, role alias) and the jobs/credentials statements in
`provisioning/iot-device.yaml`, both CloudFormation.

**Working from another machine:** clone the repo, `aws sso login --profile
busyweb-sso`, `scripts/device-secrets.sh restore pi3`, `restore-key`,
`restore-signing-key`, install `minisign` and the AWS CLI. Everything above
then works; nothing depends on a particular computer.

## Remote view over Tailscale

`http://hacklab/` (MagicDNS) serves the same UI to the maintainer. Requests
from the Tailscale side are read-only: the page shows a "Remote view" banner
and every change button is disabled until the helper switch is on
(`Turn on helping`, or open `http://hacklab/?admin=1`). While it is on, every
screen, including the kid's, shows "Uncle is helping"; it switches itself off
after two hours. The switch does not exist on the LAN side (gated on the
source address, not a password). Remote asks and flashes are logged with
`source=tailscale`; flips go to `data/helping.jsonl`.

Plug and unplug show within about a second: the server watches the serial
device nodes (`/dev/ttyUSB*`, `/dev/ttyACM*`, every `watch_interval` seconds,
default 1), reads the port list from sysfs (instant; arduino-cli's discovery,
12.7 s on a Pi 3, is used only where sysfs is absent, i.e. on a Mac) and pushes
a `status` event over `/api/events`; the page re-reads
`/api/status` on it. The 20 s poll remains as the fallback for a dropped stream.

Browser tests: `pw test "hacklab/tests/pwa/"` runs the mock-backend UI suite and the
full-stack suite (real runner on the emulated board, recorded AI answers) on
Chromium, Firefox and WebKit.

## The appliance (P5b)

On a fresh Raspberry Pi OS (64-bit) with SSH and WiFi set up:

```
sudo apt-get install -y git
sudo git clone https://github.com/Warrenn/hacklab.git /opt/hacklab/src
sudo /opt/hacklab/src/provisioning/install.sh      # idempotent; --dry-run to preview
```

Then from the maintainer's machine: `scripts/push-key.sh root@hacklab` (API key
from `.env` into the root-only `/etc/default/hacklab`) and
`provisioning/install-ops.sh <device> root@hacklab` (IoT agent, after
`scripts/provision-device.sh <device>`). Boxes whose stock code is not in git
get it under `/opt/hacklab/data/boxes/<id>/stock/<Main>/` and their genie
skeleton under `.../genie/skeleton.ino` (owner-supplied).

The app runs as the `hacklab` user on port 80 (`http://hacklab.local` from the
iPad), config in `/etc/hacklab/config.toml`, state under `/opt/hacklab/data`,
logs in journald (200 MB cap) and rotated JSONL files. comitup stops the app
while the setup hotspot owns port 80 and starts it again on home WiFi.

Re-image for the two-partition layout (deferred, needs the card in hand):
write Pi OS, shrink the root partition, add an ext4 data partition mounted at
`/opt/hacklab/data` (fstab), run `install.sh`, then enable the overlay root
(`raspi-config` > Performance > Overlay File System) so a power cut cannot
corrupt the OS. The spare card gets the same image.

## The AI helper (P4)

`ANTHROPIC_API_KEY` in the environment turns the helper on (`.env` locally; the
Pi service gets a root-only env file in P5). Each ask is one Messages API call
(`claude-sonnet-5-5`, structured output) that returns rule fragments for the
box's skeleton (`boxes/<id>/genie/skeleton.ino`, or on the device for boxes
whose stock code is not in git); the app assembles, compiles (retrying up to 3
times with the compiler error), flashes and stores the version. Spend is
logged per call under `data/spend/` (a log, not a cap). The budget lives in one
place only, the Claude Console workspace spend limit: when it is reached the
API refuses the call and the helper shows as away until the next month. Without hardware: `HACKLAB_BOARD=fake` runs the full stack on the
emulated board.

- `scripts/record-golden.py [--compile]` re-records `tests/golden/*.json` live.
- `scripts/hil-ask.sh <box> <stock-dir> <skeleton.ino> "<request>"` (on the Pi)
  asks through the real app, flashes, prints the kid message, then undoes.

## Safety for a young user

Hack Lab is used by one child, at home, on one iPad, under the owner's
supervision; it is not a public service. The measures below follow Anthropic's
Usage Policy and its guidelines for organizations serving minors.

- **It says it is an AI.** The assistant is "the AI helper" on every screen,
  with a visible here/away chip, and says plainly that it is an AI if asked.
- **Content filtering, twice.** The persona (`hacklab/genie.py`) keeps the
  helper on the box only: no personal details, no links, nothing violent or
  unsafe, nothing about sex, drugs, self-harm, hate or bullying, and a pointer
  to a trusted grown-up if the child seems upset. A code-side guard
  (`hacklab/guard.py`) then checks every answer whatever the model returned:
  fragments cannot add includes, pins, hardware setup, storage or blocking
  loops; kid-facing text cannot carry links, emoji, app mechanics or the
  instructions. A sketch that breaks a rule is sent back to the model (three
  attempts); an explanation that does is declined. The API's own refusals are
  declined the same way.
- **Red-team as a regression test.** `tests/golden/rt-*.json` are live answers
  to adversarial asks (personal details, violence, unsafe limits, prompt
  injection, links, insults, instruction leaks, code escape, adult topics,
  "are you human"); `tests/test_redteam.py` asserts the invariants on every
  one. Re-record with `scripts/record-golden.py --compile` after a persona
  change.
- **Monitoring.** Every ask, refusal, guard decision and error is logged with
  its source (`data/logs/asks.jsonl`), pulled by `scripts/logs.sh`; the owner
  reviews them. The child has no shell, no raw model access, and only the
  whitelisted compile, flash, undo and reset paths.
- **Spend.** One budget, the Claude Console workspace spend limit; when it
  trips the helper shows as away and the offline tricks keep working.
- **Access.** LAN and Tailscale only; remote viewers are read-only unless
  the owner turns helping on, which the child sees as "Uncle is helping".
- **The browser cannot be used against the box.** The app answers only for
  its own names (`hacklab.local`, `hacklab`, `localhost`, IP literals,
  Tailscale `*.ts.net`, plus `[app] allowed_hosts`) and refuses a POST whose
  `Origin` is another site, so a malicious web page open on the iPad cannot
  flash the box (CSRF, DNS rebinding). Asks are capped at 500 characters,
  a Level 3 sketch at 256 KB.
- **The service is sandboxed.** `hacklab-app.service` runs as its own user
  with `ProtectSystem=strict`, a bounding set of only `CAP_NET_BIND_SERVICE`,
  `RestrictAddressFamilies`, `SystemCallArchitectures=native` and the
  `Protect*` family; it can write only its data and the Arduino cache. The Pi
  installs security updates by itself (`unattended-upgrades`, no automatic
  reboot) and nothing listens but SSH and the app. SSH on the LAN accepts
  keys only and the login user's sudo asks for a password; the owner's remote
  path is Tailscale SSH.

For the household: `docs/family-card.md` (printable). For the first install:
`docs/field-checklist.md`.

## The code views and the Level 3 editor

Done and Tweak show the sketch in a dark panel with syntax colours and the
tweakable numbers marked; "Level 3: edit all the code" opens a real editor
(CodeMirror 6, MIT) with C++ highlighting, bracket matching, line numbers and
autocompletion seeded from the box's helper functions, remote keys and every
identifier in the sketch. It ships as one vendored bundle,
`static/vendor/editor.js`, built once from `vendor/editor/` (`npm ci && npm run
build`; versions pinned in its package.json; node_modules is git-ignored, the
bundle is committed) so the Pi needs no CDN and no Node. If the bundle fails
to load the page falls back to a plain text area.

## Explanations for the kid

On "The code right now" page, "What does this code do?" asks the AI helper for a
kid-level walk-through of the current sketch: a short story, a flow picture of
3-6 steps, one everyday metaphor and something to try on the box. Tapping a
line, then another, picks a range and "Explain lines a-b" does the same for just
those lines. Explanations run as `explain` jobs (no flash), use a separate
teaching prompt with the same safety rules and the same code-side guard, are
logged like asks, and are cached beside the version
(`data/<box>/versions/<id>/explain-*.json`) so re-reading is free. "How does the
whole thing work?" is a static page (iPad, WiFi, the Pi, the USB cable, the box,
the AI helper in the cloud) with no model call. When the screen is too narrow
for both, the code steps aside while an explanation is open and comes back
when it closes. The recorded answers live in `tests/golden/explain-*.json`
(`scripts/record-golden.py --explain`).

## Boxes

Everything box-specific lives in `boxes/<id>/` (TOML + Markdown + sketch
folders): `profile.toml` (board, libraries, where the stock code lives),
`pins.toml`, `hardware.md`, `concepts.toml`, `behaviours/<id>.toml` +
`behaviours/<id>/<id>.ino`, `templates/...`, `stock/` (only when the license
allows; otherwise the stock code is copied to `data/boxes/<id>/stock/` on the
device). Tweakable numbers use the Hack Pack IDE's trailing-comment markers,
e.g. `int shakes = 3; ///{"range":[1,10],"label":"How many shakes"}`.

- `scripts/import-box.sh <ide-slug> [--fqbn ...] [--name "..."]` (P6) turns a
  box in the Hack Pack IDE into a profile in one command: Playwright (the
  machine-wide `pw` harness, nothing installed in the repo) dumps every file of
  `ide.crunchlabs.com/editor/<slug>` to the git-ignored
  `provisioning/local/ide/<slug>.json`; `hacklab.importer` then commits a
  sketch verbatim under `boxes/<id>/stock/<Dir>/` when its main `.ino` carries
  an MIT header, and stages anything else under `provisioning/local/boxes/<id>/`
  for the device only (`location = "device"`). It scaffolds `profile.toml`,
  `pins.toml` (pins and `///{}` limits found in the sketch), `hardware.md`,
  `concepts.toml` and `genie/skeleton.ino` with the four `//@@` markers; re-runs
  refresh the stock and keep hand-edited files. Then edit the kid copy, add
  `[copy]` suggestions and any library to `provisioning/libraries.txt`, and run
  `check-box.sh`.
- `scripts/new-box.sh <id> "<Name>"` scaffolds an empty box from `boxes/_template`.
- `scripts/check-box.sh <id>` validates the profile and kid copy, then compiles
  every behaviour, template and stock sketch (local toolchain, the Pi, or the
  dev container).
- Boards: `profile.toml [board].fqbn` must be a key of
  `provisioning/boards.toml` (the board registry: core to install, USB ids to
  detect by, bootloader/cpu variants to try, whether the port re-enumerates
  after upload). Detection, flashing and the toolchain installer read it, so a
  box on a new board is a registry entry plus a profile, not a code change.
  `arduino:avr:nano` is verified on real boards; `esp32:esp32:esp32` is a
  best-effort entry awaiting a board. Deploys run the release's
  `install-toolchain.sh`, so new cores and libraries arrive with the release.

## Hardware-in-the-loop

The flash core (`hacklab/board.py`, `flash.py`, `store.py`, `RealJobRunner` in
`jobs.py`) is unit-tested on `FakeBoard`. The real path is exercised on the
Pi with a Nano-class box attached:

```
ssh root@hacklab
cd /opt/hacklab/src && git pull
PREFIX=/opt/hacklab scripts/hil-flash.sh <box-id> <stock-sketch-dir>
```

It drives the real app (`FAKE_BOARD=0`) through the HTTP API: select box,
flash a serial sketch, undo, flash, reset; prints timings, the sketch's serial
banner and the cached bootloader. Sketch versions live under
`data/<box>/versions/NNNN/<sketch>/` with `0000` as the pinned stock baseline.
arduino-cli needs the main file named after its folder (`<dir>/<dir>.ino`).

## Public repo hygiene

No secrets, no personal details. Config, keys, device identifiers and runtime
state are untracked (see `.gitignore`). CrunchLabs stock sketches are MIT and
are committed with their license headers.

## Remote ops (P5a)

The Pi reports to an AWS IoT Core device shadow every 5 minutes and is
reachable for break-glass root SSH over Tailscale. No commands are executed
remotely; updates until P5 proper are `ssh root@hacklab` + git/apt.

| Command | Does |
| --- | --- |
| `scripts/provision-device.sh <device>` | Key + CSR on your machine, CloudFormation stack (thing, cert, scoped policy) in eu-west-1, cert/endpoint/root CA into `provisioning/local/<device>/` (git-ignored) |
| `provisioning/install-ops.sh <device> [ssh-target]` | Installs/upgrades the agent on the Pi: `/opt/hacklab/ops` venv, certs 0600, `hacklab-ops.service` |
| `scripts/status.sh <device>` | Prints the shadow's reported state and its age |
| `scripts/device-secrets.sh backup\|restore\|list <device>` | Copies the git-ignored `provisioning/local/<device>/` files (cert, private key, CSR, endpoint, root CA) to/from SecureString parameters under `/hacklab/devices/<device>/` in Parameter Store (eu-west-1). `provision-device.sh` runs the backup itself; run `restore` on a new machine. `backup-key` / `restore-key` do the same for `ANTHROPIC_API_KEY` in `.env` (parameter `/hacklab/anthropic/api-key`). |

Needs `AWS_PROFILE` (default `busyweb-sso`) logged in. Agent code: `ops/agent.py`,
tests in `tests/test_ops_agent.py`.
