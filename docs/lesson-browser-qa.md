# Repeatable offline lesson browser check

Run the real lesson renderer against a generated two-second silent audio file and one caption cue:

```sh
.venv/bin/python scripts/check_lessons.py \
  --playwright /path/to/playwright-core \
  --browser /path/to/already-installed/chromium
```

The command needs an existing Node.js 18+ executable, Playwright or `playwright-core`, and Chromium. Use `--node` when Node is outside `PATH`. Omit `--playwright` when Node can already resolve the installed module; omit `--browser` when Playwright already has its browser installed. The command never downloads dependencies or library content.

The generated fixture, JSON report, and desktop/mobile screenshots are saved in `.owl/acquisition/lesson-qa/`; `--output-dir` selects a different dedicated directory. Reruns reuse only directories bearing this check's ownership marker.

Both 1280px and 390px checks open the generated HTML through `file://` with network requests blocked. They require actual audio playback, a loaded native caption cue, the complete timed transcript, no horizontal page overflow, and no browser errors or attempted remote requests. Only small verified VTT captions are embedded in the generated HTML because Chromium blocks separate caption files under `file://`; media stays in its ordinary source file, and the original caption file remains linked.

This verifies the renderer and ordinary-file playback mechanism. Publisher lesson selection, codec compatibility of acquired videos, and physical-device certification remain separate acceptance checks. A short JSON summary is printed; detailed evidence stays in `report.json`.
