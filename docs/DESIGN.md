# Hack Lab — Design Principles

As of 2026-10-28. Maintainer: the uncle. Living doc; source of truth for the *why*. STRATEGY.md is the *what* and *in what order*.

Living design doc for Hack Lab (repo hacklab): the principles we commit to, the questions we are working through, and the decisions they produce. Companion to STRATEGY.md in the repo.

## Draft principles

As stated on 2026-10-28, before any challenge. Each will be sharpened or split in the sections below.

1. **Robustness.** It must work in as many scenarios as possible. The maintainer will not be available, there are many unknowns, and things will break, so the solution needs redundancies and must be recoverable.
2. **Built for a low-attention-span child** who needs a lot of positive stimulus.
3. **The primary goal is educational**: teach programming concepts.
4. **Easy to use, but also easy to see and figure out how things work.**
5. **Give as many opportunities for feedback as possible.**

## Open questions

- [ ] Turret capability inventory: exactly what the stock hardware can do (servos, ranges, IR remote keys, fire mechanism, sensors).
- [ ] The mental model taught: is "when \<remote key> then \<turret action>" the unit of everything (library entries, templates, genie output)?
- [ ] How he corrects the system: Undo + retry, or a correction turn ("no, slower")?
- [ ] Does his mom see anything (a status page, the log), and does she get told that conversations are logged?
- [ ] First-run experience: does the app ask him to name the turret?
- [ ] AWS IoT Core: verify current pricing/free tier and Pi 3 SDK support before committing.

## Robustness and recovery

The rule that falls out of every scenario below: **there are no irreversible states, and "back to a known-good box" must always be one action away, with no AI and no internet.**

| Scenario | Must work? | Required behaviour |
| --- | --- | --- |
| Claude API unreachable (internet down) | Yes | he can still write code and flash. Helpful message explains why the helper is away. |
| Console spend limit reached (API refuses) | Yes | Same as above: coding and flashing continue, clear message. The limit is set once, in the Claude Console; the app has no cap of its own. |
| Turret unplugged / wrong port | Tolerated | Detect, show help text with a picture of the right port, no state change. |
| Flash half-completed, turret dead | Tolerated | Detect (board does not re-enumerate), offer one-tap reset to default sketch. |
| Code compiles but misbehaves (servo jitter) | Tolerated | Reset to default must be fast and obvious, to avoid hardware wear. |
| SD card corruption after power cut | Low priority | Candidate mitigations: read-only root filesystem with state on a separate partition; spare pre-imaged card in the case. |
| Impossible or off-mission request | Yes | Ask for clarification; if not possible, explain why in simple language and give the mental model so it can be intuited next time. |

**Recovery operator:** the maintainer, but only on visits months apart. Therefore a **remote operations channel** is required, independent of the deployed app, that can: report device state and status, accept commands, and apply system updates. Candidate: AWS-based queue with certificate-based device identity. Security is the primary design constraint here; remote command execution is itself the attack surface.

## The kid experience

Observed attention span: **about 10 minutes before drifting.** A full turn today is 20–60 s (model, compile, upload), so a session is roughly 5–10 turns; the design budget is one satisfying outcome per sitting.

Positive stimulus that works for him: **the turret physically doing something, and praise text.** Points, levels and badges are deferred until the core loop is solid.

## Learning model

Three stages, moving from AI-as-author to AI-as-helper:

1. **Magic genie (MVP).** Plain-language request, the system writes and flashes the code. Code is visible on request.
2. **Guided editing.** The system shows the code it wrote, names what it changed, and invites small edits; AI explains and fixes rather than rewriting.
3. **Author with a helper.** he edits the code himself; AI answers questions, explains compiler errors, suggests next steps.

The robustness requirement forces stage 3's editor to exist from the start: when Claude is unavailable, the no-AI path is write-or-edit code, compile, flash. The MVP ships the genie on top of that path, not instead of it.

**The unit of work is a rule: "when ⟨trigger⟩ → ⟨action⟩".** Library entries, templates and genie output all take this shape. Loops, conditions, timing and variables are introduced when a request needs them ("repeat 3 times", "only if", "wait 2 seconds"), not by lecture.

**Curiosity prompts.** After each change, the system offers at most 3 context-relevant invitations to learn more, in his terms: "Want to know how the servo motors make it shake its head?", "Want to see how to write a conditional?". Each opens a short, in-app explanation written for him, with no outbound links. External links (videos, articles) are cut from the MVP: any link to YouTube is a side door to content he is not supposed to watch. If links return later they come from a maintainer-curated, vetted catalogue in the repo, never from live web search.

### Scope: all Hack Pack boxes, not only the turret

The Hack Pack IDE lists 17 boxes (IR Turret, Domino Robot, Label Maker, Sand Garden, Laser Tag, Laser Synthesizer, Nixie Clock, Balance Bot, RoboLamp, Omnibot Forklift, Tank Plant, Card Dealing Bot, String Plotting Robot, Color Composer, Space Oddity, Robot Ranger). The boxes with public build write-ups use an Arduino Nano-compatible board programmed over USB (sources: [Hack Pack IDE](https://ide.crunchlabs.com/), [Balance Bot build](https://www.technodabbler.com/crunchlabs-balance-bot-build-balance-and-tune/), [IR Turret build](https://www.technodabbler.com/crunchlabs-ir-turret-build-code-and-fire/)). Not yet verified for every box.

So the compile/flash core is shared, and everything box-specific lives in a **box profile**:

| Profile element | Example (IR Turret) |
| --- | --- |
| Hardware spec for the system prompt | 3 servos (pan, tilt, roll/fire), IR receiver, remote key map |
| Pin map and safe ranges | servo limits clamped |
| Library whitelist | Servo, IRremote |
| Stock sketch (user-supplied, untracked) | from the Hack Pack IDE |
| Behaviour library (offline, pre-tested) | shake head, sweep, fire on key |
| Templates with tweakable values | key number, angle, delay |
| Concept map | servo, event, loop, delay |
| Curated links | ≤ 4 per concept |

The Pi cannot tell boxes apart over USB (same chip), so the app needs a "which box is on the desk?" picker with pictures, remembered until changed.

## Feedback loops

| From | To | What |
| --- | --- | --- |
| Box | Nephew | The physical result: the primary reward. |
| System | Nephew | Progress during the wait, praise on success, helpful assistance and advice on failure, mental-model explanations when something cannot be done. |
| System | Maintainer | A robust, durable log of every request, generated sketch, compile result, flash result and error, examinable remotely. |
| Nephew | System | Open: how he says "that is not what I meant" (Undo plus a retry, or a correction turn). |

## Decision log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-10-28 | The no-AI path (edit, compile, flash, reset) is the foundation; the genie is a layer on top. | Must work with Claude unavailable; also makes learning stage 3 exist from day one. |
| 2026-10-28 | Offline coding = (a) library of ready-made, pre-tested behaviours + (b) template editing with tweakable values highlighted. Block-based editor deferred to stage 2/3. | Raw C++ plus a compiler error with no helper loses an 11-year-old inside the 10-minute budget. |
| 2026-10-28 | Remote ops = AWS IoT Core (per-device X.509 cert, device shadow for state, Jobs for updates, MQTT for logs) + Tailscale SSH with root as break-glass. No arbitrary remote command execution over the queue. | Independent of the deployed app; signed allowlisted jobs instead of a command channel; SSH authenticates on WireGuard keys. Pricing and free tier to be verified before commit. |
| 2026-10-28 | Physical reset button on the case: not now; revisit once usage is observed. |  |
| 2026-10-28 | Waiting time is designed: live progress during the 20–60 s flash; the first turn of every session is a pre-tested suggestion guaranteed to succeed. | 10-minute attention budget, 5–10 turns per session. |
| 2026-10-28 | SD resilience: read-only root filesystem with a small writable partition, plus a spare pre-imaged card kept in the case. | Both are cheap; a power cut cannot corrupt the OS. |
| 2026-10-28 | Points, levels, badges deferred until the core loop is solid. | Avoid building a slot machine before the learning loop works. |
| 2026-10-28 | Scope is the whole Hack Pack, not only the turret. Box-specific knowledge lives in a box profile; the core is shared. | the nephew has several boxes; all use Nano-class boards over USB \[VERIFY per box\]. |
| 2026-10-28 | Mental model = "when trigger → action" rules; concepts introduced by need. | One structure for library, templates and genie output; teachable and safe. |
| 2026-10-28 | Curiosity prompts (≤ 3) with curated links (≤ 4 each) from a vetted in-repo catalogue; no live web search at runtime. | Child-safe, mom-approvable, works offline. |
| 2026-10-28 | Correction = Undo + re-ask for the MVP. | Conversational correction doubles prompt complexity. |
| 2026-10-28 | No status page for mom; consent for logging already given; all content child-friendly; some videos may need her approval. |  |
| 2026-10-28 | The lab already has a name; the name is for the lab, not one box. |  |
| 2026-10-28 | Curiosity prompts stay in the MVP, but open in-app explanations only. No external links of any kind. | A YouTube link is a side door to content he is not supposed to watch. |
| 2026-10-28 | Product name: Hack Lab (repo is hacklab). The nephew's name never appears in the public repo. The AI is called "the AI helper" with a visible here/away status. | Box-agnostic; privacy; a mental model that matches reality (sometimes away, he and the box always there). |
| 2026-10-28 | Borrow the Hack Pack IDE's levels: Level 1 AI does it (default), Level 2 change the numbers, Level 3 edit all the code (always available, never default). Adopt their ///{"range":\[a,b\]} trailing-comment markers for tweakables. | Vocabulary he already knows from the kit; stock sketches become Level 2 templates with no editing. |
| 2026-10-28 | Stock sketches are committed: CrunchLabs code is MIT-licensed (verified in the IDE for IR Turret and Laser Synthesizer). | Removes the user-supplied-at-install step; official hacks seed the behaviour library. |
| 2026-10-28 | Docker is dev-only (arm64 Debian on the Mac, FAKE\_BOARD). No Docker on the Pi. Deploys are signed release tarballs applied by the ops agent via IoT Jobs, with health check and auto-rollback. A set of maintainer scripts covers new box, check, release, deploy, rollback, status, logs. | Same toolchain on Mac and Pi; nothing hand-edited on the device; new boxes are content, not code. |
| 2026-10-31 | The AI budget has exactly one home: the Claude Console workspace spend limit. The app keeps a spend log but enforces no cap of its own. | Owner: two places to set a budget drift and the wrong one trips first. The API returns 400 `invalid_request_error` when the Console limit is reached (and 429 at the tier cap); the app already treats any API error as "the AI helper is away". |
| 2026-10-31 | Release signing stays on the maintainer's machine; no CI signing. "Work from any machine" is met by `scripts/device-secrets.sh restore-signing-key` (encrypted backup in Parameter Store), not by putting the key in a CI secret. | A CI secret is a third copy in a third place; the key custody decision (outside AWS, owner-held) stands. |
| 2026-10-31 | The ask is a conversation that ends in the AI helper's answer; only a "ready" answer enables Go!, which flashes the plan the helper is holding. One Send button, one Go! button, a multiline box whose draft survives screen rebuilds; "Try one of these" hides while the kid types. | Owner's report on the preview: a half-typed request vanished (the screen is rebuilt on status events), and the helper, not the page, knows when it has enough to act. No redirect to Working while a question is open. Departs from Main.dc.html by the owner's request. |


## Screens

The MVP screens are in `docs/screens/` as `.dc.html` source (the markup inside `<x-dc>` is plain HTML with inline styles; the `<script type="text/x-dc">` block is mock interaction state). Treat them as the visual spec for P3: layout, copy, button names and positions. The live canvas is "Hack Lab Screens" in the maintainer's Claude artifacts.

| File | Screen |
| --- | --- |
| Main.dc.html | Home: ask box, 3 pre-tested suggestions, current state, Undo / Back-to-how-it-came |
| Working.dc.html | 4-stage progress with a one-line explanation of what is happening |
| Done.dc.html | Praise, curiosity prompts (in-app explanations), code with tweakables highlighted, Level 3 link |
| BoxPicker.dc.html | Which box is plugged in (picture cards) |
| Offline.dc.html | Home when the AI helper is away: offline tricks grid, same rescue buttons |
| Tweak.dc.html | Level 2: sliders bound to the ///{range} markers, live code, plain-language summary |

Known inaccuracy to fix in P2/P3: the Done and Tweak mock code uses `pan.write(angle)`; the real turret's yaw servo is continuous-rotation (speed + time), see STRATEGY.md findings.
