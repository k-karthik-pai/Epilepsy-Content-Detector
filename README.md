# Epilepsy Content Detector

Windows-first desktop guard that watches the screen for photosensitive-epilepsy
risk patterns and instantly covers every monitor with a black shield when the
content looks unsafe.

## Current Status

This is an early clinical-assistive prototype. It implements:

- Native Windows screenshot capture through Win32 APIs.
- Guideline-inspired detection for large-area luminance flashes, saturated red
  flashes, rapid cuts, and high-contrast regular patterns.
- A topmost black blackout shield for all monitors.
- Fail-closed behavior when capture becomes unreliable.
- Synthetic tests that exercise risky patterns without displaying dangerous
  flashing visuals.

It is not a certified medical device and cannot guarantee seizure prevention.
See [docs/SAFETY.md](docs/SAFETY.md).

## Run

Requires Python 3.11+ on Windows. No third-party Python packages are required.

```powershell
python -m epilepsy_guard
```

Analyze one frame per monitor without starting the shield:

```powershell
python -m epilepsy_guard --once
```

Print a full example config:

```powershell
python -m epilepsy_guard --print-example-config
```

## Emergency Unlock

Hold `Ctrl + Alt + U` for the configured unlock duration. By default this hides
the shield for 10 seconds so the unsafe content can be closed or moved away.

## Test

```powershell
python -m unittest discover -s tests
```
