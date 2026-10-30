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
`pw test tests/pwa` (machine-wide Playwright harness; set `HACKLAB_PYTHON` if the
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

## The AI helper (P4)

`ANTHROPIC_API_KEY` in the environment turns the helper on (`.env` locally; the
Pi service gets a root-only env file in P5). Each ask is one Messages API call
(`claude-sonnet-5-5`, structured output) that returns rule fragments for the
box's skeleton (`boxes/<id>/genie/skeleton.ino`, or on the device for boxes
whose stock code is not in git); the app assembles, compiles (retrying up to 3
times with the compiler error), flashes and stores the version. Spend is
logged per call under `data/spend/` and the helper switches off at
`monthly_cap_usd` (config) until next month; set the same cap on the Console
workspace. Without hardware: `HACKLAB_BOARD=fake` runs the full stack on the
emulated board.

- `scripts/record-golden.py [--compile]` re-records `tests/golden/*.json` live.
- `scripts/hil-ask.sh <box> <stock-dir> <skeleton.ino> "<request>"` (on the Pi)
  asks through the real app, flashes, prints the kid message, then undoes.

## Boxes

Everything box-specific lives in `boxes/<id>/` (TOML + Markdown + sketch
folders): `profile.toml` (board, libraries, where the stock code lives),
`pins.toml`, `hardware.md`, `concepts.toml`, `behaviours/<id>.toml` +
`behaviours/<id>/<id>.ino`, `templates/...`, `stock/` (only when the license
allows; otherwise the stock code is copied to `data/boxes/<id>/stock/` on the
device). Tweakable numbers use the Hack Pack IDE's trailing-comment markers,
e.g. `int shakes = 3; ///{"range":[1,10],"label":"How many shakes"}`.

- `scripts/new-box.sh <id> "<Name>"` scaffolds a box from `boxes/_template`.
- `scripts/check-box.sh <id>` validates the profile and kid copy, then compiles
  every behaviour, template and stock sketch (local toolchain, the Pi, or the
  dev container).

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
| `scripts/device-secrets.sh backup\|restore\|list <device>` | Copies the git-ignored `provisioning/local/<device>/` files (cert, private key, CSR, endpoint, root CA) to/from SecureString parameters under `/hacklab/devices/<device>/` in Parameter Store (eu-west-1). `provision-device.sh` runs the backup itself; run `restore` on a new machine. |

Needs `AWS_PROFILE` (default `busyweb-sso`) logged in. Agent code: `ops/agent.py`,
tests in `tests/test_ops_agent.py`.
