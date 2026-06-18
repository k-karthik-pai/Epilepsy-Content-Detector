# Epilepsy Content Detector

Windows-first desktop guard that watches the screen for photosensitive-epilepsy
risk patterns and instantly covers every monitor with a black shield when the
content looks unsafe.

## Current Status

This is an early clinical-assistive prototype. It implements:

- Native Windows screenshot capture through Win32 APIs.
- A capture-backend interface with GDI as the current default backend.
- Low-resolution 40 FPS analysis capture for faster detection latency.
- Guideline-inspired detection for large-area luminance flashes, saturated red
  flashes, localized windowed flashes, rapid cuts, and high-contrast regular
  patterns.
- Polarity-coherence filtering so mixed page changes such as normal tab
  switching do not look like coherent flashes.
- Automatic monitor topology refresh for docking, display connection, and
  resolution/layout changes.
- Shield self-capture protection with detector reset and a short rearm grace on
  PCs where Windows cannot exclude the blackout overlay from capture.
- Single-instance enforcement for live protection, preventing duplicate capture
  loops and competing blackout overlays.
- Automatic capture-session rebuild after repeated backend errors, with
  interruptible retry backoff for responsive shutdown.
- Bounded decision queue with guaranteed BLOCK preservation if the UI thread is
  temporarily busy.
- Thread-safe, non-fatal diagnostic logging so disk errors cannot stop capture
  or delay the blackout shield.
- A topmost black blackout shield for all monitors, with a maximum duration so
  it cannot stay black indefinitely.
- Bounded rotating JSONL logs for diagnostics without unbounded disk growth.
- Capture-error logging without blacking out on capture failures.
- Synthetic tests that exercise risky patterns without displaying dangerous
  flashing visuals.

It is not a certified medical device and cannot guarantee seizure prevention.
See [docs/SAFETY.md](docs/SAFETY.md) and
[docs/PRODUCT_READINESS.md](docs/PRODUCT_READINESS.md).

## Run

Requires Python 3.11+ on Windows. No third-party Python packages are required.

```powershell
python -m epilepsy_guard
```

After installing the package, the equivalent command is:

```powershell
epilepsy-guard
```

Analyze one frame per monitor without starting the shield:

```powershell
python -m epilepsy_guard --once
```

Measure actual Windows capture speed on the PC:

```powershell
python -m epilepsy_guard --benchmark-capture
```

Estimate live block latency for synthetic risky scenarios without displaying
flashing content:

```powershell
python -m epilepsy_guard --benchmark-latency
```

Run local diagnostics for config, capture, monitor, shield, and latency health:

```powershell
python -m epilepsy_guard --health-check
```

Print a full example config:

```powershell
python -m epilepsy_guard --print-example-config
```

The default config uses `"capture_backend": "gdi"`. Future backends can use the
same app/detector/shield pipeline. Logs default to `log_max_bytes` of 1000000
and `log_backup_count` of 5.

Run without showing the blackout shield while you test normal desktop activity:

```powershell
python -m epilepsy_guard --monitor-only --print-events
```

Run a timed live smoke test for 10 seconds:

```powershell
python -m epilepsy_guard --monitor-only --print-events --duration 10
```

Run safe synthetic detector checks without displaying flashing content:

```powershell
python -m epilepsy_guard --simulate safe-browser
python -m epilepsy_guard --simulate safe-tab-switch
python -m epilepsy_guard --simulate general-flash
python -m epilepsy_guard --simulate windowed-flash
python -m epilepsy_guard --simulate small-windowed-flash
python -m epilepsy_guard --simulate red-flash
python -m epilepsy_guard --simulate regular-pattern
```

Show the black shield briefly only after a synthetic risky sequence is detected:

```powershell
python -m epilepsy_guard --simulate general-flash --simulate-shield --duration 2
python -m epilepsy_guard --simulate windowed-flash --simulate-shield --duration 2
python -m epilepsy_guard --simulate small-windowed-flash --simulate-shield --duration 2
```

The shield also auto-releases after the configured `max_blackout_seconds`
default, even on PCs where Windows capture-exclusion does not work.

## Emergency Unlock

Hold `Ctrl + Alt + U` for the configured unlock duration. By default this hides
the shield for 10 seconds so the unsafe content can be closed or moved away.

## Test

```powershell
python -m unittest discover -s tests
```
