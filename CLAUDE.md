# CLAUDE.md — turret-lab

Read STRATEGY.md first; it is the source of truth for scope, constraints, and
phase order. Do not start a phase out of order without being asked.

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
   credentials, Tailscale identifiers, the nephew's personal details, or the
   CrunchLabs stock sketch (unverified license — user-supplied at install time).
   Check every commit against the hygiene list in STRATEGY.md.

## Safety context

The end user of the deployed system is an 11-year-old. All persona/system-prompt
work must stay age-appropriate, and the Anthropic API integration must follow
Anthropic's guidelines for products serving minors (content filtering, logging,
spend caps). The kid never gets shell access, raw model access, or unreviewed
tool calls beyond the whitelisted compile/flash/rollback tools.
