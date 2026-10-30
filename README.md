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

## Hardware-in-the-loop

No board-touching code yet. The manual HIL smoke script arrives with the flash
core in P1 and is documented here.

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

Needs `AWS_PROFILE` (default `busyweb-sso`) logged in. Agent code: `ops/agent.py`,
tests in `tests/test_ops_agent.py`.
