# v1.1.1 development build — Software mute/solo resilience and recovery

This guide is for the **current** v1.1.1 development build application with the software
mute/solo safety patch. This change does **not** add mute hardware registers or
alter device routing. It safeguards gain-matrix muting on exact-profile DICE/RME
hardware, plus previously emulated output mutes on models such as MOTU.

## Important safety notes

- Test with **monitor and headphone volumes turned down**. A recovery action
  can raise a previously silent channel or output to its original level.
- Software mute and solo affect the **internal mixer path only**. A signal
  connected directly through the DICE router may bypass these controls.
- The recovery system does **not** remember or restore direct crossbar routes.
- If FFADO, the interface, or the webmixer process crashes, webmixer does **not**
  automatically restore old gain settings on its next launch. You must choose.
- Once a software-mute operation writes zero to FFADO's matrix, that physical
  crosspoint can remain at zero even if the webmixer process crashes.

## What now happens

### Normal mute and solo

1. Webmixer reads the current hardware coefficient.
2. It saves the original level in a per-device, crash-safe journal **before**
   sending the hardware's `MatrixMixer.setValue(..., 0)` call.
3. It verifies the returned hardware value; a failed write is reported rather
   than just changing the visual button state.
4. Unmuting restores the remembered level and removes the journal entry **only
   after** a successful hardware readback.
5. Multiple software solos can coexist. A user's own mute remains active after
   all solos are released. An unsuccessful multi-channel solo attempts rollback,
   with any un-restored values kept in the journal.

The journal lives alongside the per-device settings file, at a path such as:

```text
~/.config/ffado-webmixer/devices/<GUID>.mute-recovery.json
```

### Interrupted session (power outage, SIGKILL, crash)

When the application starts again and finds a saved journal, it shows a recovery
banner at the top of the mixer, identifying the number of previously suppressed
channel and/or output levels.

- **Restore levels**: after you lower the monitor volume and confirm, restore
  only hardware values which are **still at zero**. Values changed externally
  to a nonzero level are **never overwritten**. Failed writes stay in the
  recovery file so you can retry.
- **Keep current levels**: discard the saved levels and **leave the hardware
  exactly as it is now**. This can leave some channels at zero; you can adjust
  those afterward using the ordinary mixer controls.

Until the pending recovery is resolved, new software-mute and matrix-gain
operations are blocked so they cannot destroy the remaining saved values.

An unreadable or mismatched recovery journal also fails closed: webmixer will
warn rather than guessing or overwriting it. The **Keep current levels**
button can safely discard the damaged record without writing hardware gain.

### External changes

If another program or the hardware itself changes a suppressed matrix crosspoint
to a **nonzero** value, webmixer treats the external level as authoritative and
avoids overwriting it with a stale remembered gain. It cancels the affected
software-mute or solo state, and reports a warning. The read-only matrix/state
snapshots also check for these changes.

There is no reliable way to distinguish a channel that another client explicitly
set to **zero** from one still zero due to webmixer mute. Those cases remain
covered by the journal rather than being guessed.

### Normal exit

Webmixer makes a best-effort attempt to restore software-muted matrix and output
levels on normal process exit. An unavailable D-Bus server or failed hardware
readback can prevent this, in which case the saved recovery information remains.

## Safe physical test sequence

1. Back up the interface's normal mixer configuration and lower monitoring
   volume. Note a channel's gain and its route to the monitored mix bus.
2. Click **Mute** on one audible matrix input. The signal should become silent
   **only on the mixer paths controlled by that gain matrix**.
3. Change that fader's gain while it is muted. It should stay silent. Unmute:
   the new target gain should return, not the old gain.
4. Apply **Solo** to one channel, then add and remove a second Solo. Other
   channels should be restored to their previous gains when Solo is cleared;
   independently muted channels should stay muted.
5. While muted, change one suppressed crosspoint to a nonzero value in the
   original `ffado-mixer`. Refresh the webmixer state. The external value should
   remain unchanged and no stale restoration should overwrite it.
6. Test a normal application exit while one channel is software-muted, then
   reopen and compare the matrix values with the original `ffado-mixer`.
7. Only if comfortable with the procedure, test interruption using a harmless
   debug fixture (see below) **before** simulating any physical crash.
8. After an interrupted session, inspect the recovery banner. Test both
   actions in separate sessions, always with low monitor volume.
9. For MOTU output faders that have no native mute control, check that a
   failed restoration does not lose the saved pre-mute output level.

## Offline simulated test (no D-Bus)

```bash
python main.py --debug profire2626 --headless
```

This simulation logs intended D-Bus operations without sending them. No real
hardware changes happen. Because debug mode has no persistent recovery journal,
crash recovery itself is covered by the automated mock-hardware test suite:

```bash
python -m unittest discover -s tests -p 'test_soft_mute_recovery.py' -v
```

## Report issues to the project maintainer / ChatGPT

You do **not** need to diagnose the issue yourself. Send:

1. Device make/model, FireWire GUID, Linux distribution and FFADO version.
2. Whether the problem involves **Mute**, **Solo**, **Restore levels**, or
   **Keep current levels**; specify selected bus and channel.
3. Exact steps to reproduce, expected result, audible result, and whether the
   value changed in the original `ffado-mixer`.
4. Complete terminal traceback/errors from webmixer, and a screenshot of the
   button state or recovery banner.
5. Read-only snapshots immediately before and after the problem:

```bash
curl -sS http://127.0.0.1:5000/api/describe > ffado-describe.json
curl -sS http://127.0.0.1:5000/api/state?mix=0 > ffado-state.json
curl -sS http://127.0.0.1:5000/api/mute-recovery > ffado-mute-recovery.json
curl -sS http://127.0.0.1:5000/api/matrix > ffado-matrix.json
```

Change `mix=0` to the affected bus index if needed. The commands above are
**GET requests only**; they do not change the interface. Avoid posting the
contents of private system files unrelated to the mixer.

For a crash-recovery problem, also attach a **redacted copy** of
`~/.config/ffado-webmixer/devices/<GUID>.mute-recovery.json`, if present.
It contains the GUID, source-defined matrix path, and saved audio levels—not
passwords. Do not hand-edit or delete it before capturing the bug report.

## Implementation limitations

- Runtime FFADO responses can fail even when the offline test doubles succeed.
- No background daemon continues to manage software mute/solo after webmixer
  terminates. At shutdown, restoration is best effort; after a crash it is
  user-confirmed.
- An external write which keeps a gain at zero cannot be distinguished from
  a still-muted channel using the available FFADO D-Bus value alone.
- Software mute cannot silence an audio path bypassing the hardware's internal
  mixer matrix.
