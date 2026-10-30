# CLAUDE.md — Hack Lab (repo: hacklab)

Read, in this order, before any work:
1. STRATEGY.md — the WHAT and the ORDER: scope, constraints, architecture, box
   profile schema, API contract, phases, maintainer scripts, IDE findings.
2. docs/DESIGN.md — the WHY: principles, the kid experience, learning model,
   robustness table, and the decision log. A decision there is settled; do
   not re-open it without being asked, and append to the log when a new one
   is made.
3. docs/screens/*.dc.html — the visual spec for the PWA (P3): plain HTML with
   inline styles inside `<x-dc>`, plus a mock-state script. Match layout,
   copy, button names and positions; ignore the mock JS.

Do not start a phase out of order without being asked.

## Workflow rules

1. Before writing code: ask clarifying questions, then present an implementation
   plan/breakdown for the phase, then summarize findings. Wait for approval.
2. Any agreed change to the plan gets written back into STRATEGY.md before
   implementation.
3. Write tests for all new/changed code, run them, and keep fixing until all
   tests pass before marking a task done. Hardware-touching code: mocked unit
   tests + update the manual hardware-in-the-loop script.
4. Verify present-tense facts (library versions, Anthropic API capabilities,
   arduino-cli flags, Pi OS tooling) via live search/docs, not memory. Items
   marked [VERIFY] in STRATEGY.md must be verified before the code that depends
   on them is written.
5. This is a PUBLIC repository. Never commit: secrets, API keys, WiFi
   credentials, Tailscale/IoT identifiers, or the nephew's name or any
   personal details (say "the nephew"). CrunchLabs stock sketches are MIT and
   are committed with their license headers. Check every commit against the
   hygiene list in STRATEGY.md.
6. Kid-facing copy: the AI is "the AI helper"; levels are "Level 1/2/3" as in
   STRATEGY.md; no emoji; no external links of any kind.

## Safety context

The end user of the deployed system is an 11-year-old. All persona/system-prompt
work must stay age-appropriate, and the Anthropic API integration must follow
Anthropic's guidelines for products serving minors (content filtering, logging,
spend caps). The kid never gets shell access, raw model access, or unreviewed
tool calls beyond the whitelisted compile/flash/rollback tools.
