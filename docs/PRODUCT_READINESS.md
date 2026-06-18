# Product Readiness Review

This review treats the current repository as a Windows prototype that should
evolve into a polished, mass-market desktop safety product.

## Codebase Map

- `epilepsy_guard/app.py`: CLI entrypoint, capture loop, Tk event loop,
  shield routing, synthetic simulations, and benchmark commands.
- `epilepsy_guard/capture_backends.py`: capture backend interface and current
  GDI backend adapter.
- `epilepsy_guard/detector.py`: deterministic photosensitive-risk detector for
  flashes, localized windowed flashes, red flashes, rapid cuts, and regular
  patterns.
- `epilepsy_guard/win32_screen.py`: native Win32 monitor enumeration, GDI screen
  capture primitives, capture exclusion, and emergency hotkey polling.
- `epilepsy_guard/screen_capture.py`: one capture session per monitor, producing
  downscaled `ScreenFrame` objects.
- `epilepsy_guard/shield.py`: topmost black overlay windows and emergency unlock.
- `epilepsy_guard/config.py`: JSON config loading, coercion, validation, and
  default log path resolution.
- `epilepsy_guard/logging_utils.py`: JSONL event logging.
- `epilepsy_guard/synthetic.py`: safe in-memory frame scenarios for tests and
  demos without displaying flashing content.
- `tests/`: detector, config, and app-routing regression tests.

## Current Strengths

- No third-party runtime dependencies.
- Capture is now behind a backend interface, with GDI as the current default and
  a clearer path to Desktop Duplication or Windows Graphics Capture.
- Synthetic tests cover fullscreen flashes, red flashes, regular patterns,
  browser-like safe transitions, repeated tab switching, windowed flashes, and
  small off-center windows.
- `--benchmark-capture` and `--benchmark-latency` expose real performance on the
  target PC without displaying flashing content.
- `--health-check` gives a local diagnostics surface for config, capture,
  monitors, shield capability, and latency estimates.
- The shield has manual unlock, maximum-duration release, and capture-failure
  behavior that avoids fail-closed false blackouts.
- Config validation now rejects ambiguous booleans, invalid ratios, impossible
  grids, and non-positive timing/count settings.
- JSONL logs are bounded by size and backup count, preventing unbounded disk
  growth during long-running deployments.
- Capture sessions and shield windows refresh automatically when monitor
  topology changes.
- Flash decisions require coherent luminance direction, reducing false
  blackouts from mixed bright/dark page changes during tab switching.
- When Windows cannot exclude shield windows from capture, analysis pauses on
  the overlay and detector state is rearmed after release to prevent feedback
  blackout loops.
- Live protection is single-instance, preventing duplicate capture loops and
  overlapping shields.
- Repeated capture failures automatically rebuild backend sessions, and retry
  waits are interruptible during shutdown.
- Packaging exposes an `epilepsy-guard` console entry point and explicit
  setuptools build configuration.

## Industry-Ready Gaps

- Capture backend: GDI capture is easy to ship but not the right long-term
  backend for a high-volume product. The new backend interface should be backed
  by Desktop Duplication or Windows Graphics Capture, keeping GDI as fallback.
- Process model: the detector and UI currently run in one desktop process. A
  resilient product should split capture/detection, shield control, and UI/tray
  state so one component can restart without losing protection.
- UX: there is no tray UI, onboarding, current-protection status, paused state,
  policy surface, or guided emergency-unlock flow.
- Deployment: there is no signed installer, autostart registration, enterprise
  policy template, update channel, rollback, or crash reporting.
- Observability: bounded JSONL logs and health checks are useful for debugging
  but not enough for fleet diagnosis. A production build needs
  privacy-preserving health metrics, local diagnostics export, and explicit
  user/administrator consent controls.
- Validation: synthetic tests are necessary but not sufficient. Production
  readiness needs a large curated offline corpus, hardware matrix, browser/app
  matrix, multi-monitor/DPI coverage, and latency/false-positive budgets.
- Safety governance: public guidelines are referenced, but production release
  needs documented clinical review, risk management, human-factors testing,
  clear labeling, and a maintained post-release incident process.
- Privacy/security: screen pixels are processed locally today, which is good.
  This needs to remain a hard product guarantee with code signing, tamper
  resistance, log redaction, and explicit handling for crash dumps.

## Recommended Roadmap

1. Reliability foundation:
   Extend the new health-check command into structured diagnostics export, add
   watchdog restart behavior and crash recovery.

2. Capture backend upgrade:
   Implement Desktop Duplication or Windows Graphics Capture behind the new
   capture interface. Keep the current GDI backend as fallback and benchmark
   both on startup.

3. Product shell:
   Add a native tray app with protection status, benchmark results, pause/snooze,
   emergency-unlock instructions, and a safe test mode that never displays
   flashing content.

4. Installer and fleet deployment:
   Ship a signed installer with autostart, uninstall cleanup, policy-managed
   config, versioned migration, and enterprise defaults.

5. Validation pipeline:
   Build a reproducible offline test corpus and CI gates for detection latency,
   false positives, false negatives, monitor layouts, DPI scaling, and shield
   coverage.

6. Clinical and legal readiness:
   Formalize intended use, warnings, residual risks, clinician review, support
   process, privacy posture, and release criteria before calling it a medical or
   patient-protection product.

## Next Best Engineering Step

The highest-leverage next implementation is a capture-backend abstraction with
a Desktop Duplication or Windows Graphics Capture implementation. The current
GDI backend is useful as a fallback, but a mass-market product needs lower and
more predictable capture latency across GPUs, browsers, games, and multi-monitor
setups.
