# Field checklist: first install at the nephew's home

Owner runs this on the visit, in order. Tick each line; anything that fails
goes into STRATEGY.md "P7 notes" with what was seen.

## Before leaving

- [ ] `scripts/status.sh` shows the Pi online with the current release.
- [ ] `scripts/device-secrets.sh backup` ran this week (certificates, key).
- [ ] Spare SD card imaged (deferred item; skip if not yet made).
- [ ] Print `docs/family-card.md`, write the number on it.
- [ ] Pack: Pi + power supply, USB cable for the box, the IR remote, darts.

## Network

- [ ] Power the Pi on the home router's WiFi. Within ~2 min the hotspot
      **hacklab-setup** appears (the Pi does not know this WiFi yet).
- [ ] On the iPad, join hacklab-setup; the captive page opens by itself.
      Pick the home WiFi, enter its password. The hotspot disappears.
- [ ] iPad back on the home WiFi: `http://hacklab.local/` opens the picker.
      If the router does not pass mDNS between its bands, note the Pi's IP
      from `scripts/status.sh` and test `http://<ip>/` as the fallback.
- [ ] Add the page to the iPad Home Screen (Share, Add to Home Screen).
- [ ] From your phone on mobile data: `http://hacklab/` over Tailscale shows
      the remote view (read only); `?admin=1` turns helping on; the iPad shows
      "Uncle is helping"; turn it off again.

## The box

- [ ] Plug the box in. The chip reads "plugged in" within two seconds.
- [ ] Tap the box's card, home screen shows the right name and asks. Tap the Hack Lab mark at the top to get back to the picker.
- [ ] One pre-tested trick: watch the four stages, the box does it, Done shows
      the code with the highlighted numbers.
- [ ] Change the numbers (Level 2), Send: the box changes.
- [ ] Undo, then Back to how it came: stock behaviour returns.
- [ ] One real ask to the AI helper, spoken through the keyboard mic.
- [ ] Unplug the box: "not plugged in" within two seconds. Plug back in.

## Resilience

- [ ] Pull the Pi's power mid-idle, plug back in: page back within ~90 s,
      box selection may need re-picking (known).
- [ ] Turn the router's internet off (or block the Pi): within a minute the
      Home screen becomes the Offline screen; a trick still flashes. Internet
      back: "AI helper is here" returns on its own.
- [ ] Watch `scripts/logs.sh` once from your phone to confirm log upload works
      from this network.

## Hand-over

- [ ] Show the nephew: ask, trick, Undo, Back to how it came. Nothing else.
- [ ] Show the parent the family card and the two rescue buttons.
- [ ] Note the router model and whether mDNS worked, in STRATEGY P7 notes.

## Power (added 2026-10-31)
- [ ] Use a 5 V / 2.5 A supply and a short, thick USB cable for the Pi. On the Pi,
  `vcgencmd get_throttled` must print `throttled=0x0`; `0x50005` means the supply is
  too weak and the Pi can reset by itself ("Undervoltage detected!" in the log).
- [ ] If the boxes draw from the Pi's USB, put them behind a powered hub.
