# Repeatable PhET offline browser checks

The portable manifest in `catalog/acquisition/phet-browser-checks.json` preserves the sixteen exact source pins and two viewports used for the recorded run. Its destinations are filenames relative to the PhET directory, so it works against either an existing flat acquisition cache or a built library's `REFERENCE/EDUCATION/PHET` directory.

```sh
node scripts/check_phet.cjs \
  --manifest catalog/acquisition/phet-browser-checks.json \
  --root /path/to/LIBRARY/REFERENCE/EDUCATION/PHET \
  --output .owl/acquisition/phet-qa/report.json \
  --playwright /path/to/playwright-core \
  --browser /path/to/already-installed/chromium
```

Use existing Node.js 18+, Playwright and Chromium; the script installs or downloads nothing. Installed modules and browser binaries may use their normal defaults instead of explicit paths. Add `--screenshots .owl/acquisition/phet-qa` to save screenshots. The command exits nonzero when any check fails and prints only a bounded summary.

The portable summary is preserved in `catalog/acquisition/phet-browser-evidence.json`, with no machine paths. It records the exact raw report's SHA-256, source pins, manifest hash, viewports, layout, errors, blocked request hosts, and meaningful before/after/reset values. The full report stays locally at `.owl/acquisition/phet-finish/all-report-bound.json`. All sixteen source pins match the active catalog. The current run records **32 passing checks out of 32** at 1280×900 and 390×844.

Each simulation has explicit meaningful `expected_changed_keys`. Older canvas editions use reviewed `entry`, `interaction` and `reset` scene paths, resolved to screen coordinates at either viewport. Actual actions use mouse or keyboard input; JavaScript only reads geometry and model state. Hidden ancestors, empty bounds, ambiguous actions and unreviewed state changes cannot pass. `--inspect-only` performs the configured entry and then records bounded scene geometry without interaction/reset or certification; this makes new control review repeatable. Use `--help` for action formats.

The review covers voltage/current, pendulum length, projectile speed, laser power, gas temperature, adding a proton, dispensing liquid, adding a mate, fraction numerator, area dimensions and other manifest-specified controls. Every required value changed and reset. Optional analytics/update requests were blocked. Representative mobile screenshots were inspected; the simulations preserve native letterboxed layouts and some controls are small, so viewport success does not establish touch usability.

Freeze a bounded portable summary from the detailed report with:

```sh
python scripts/summarize_phet.py .owl/acquisition/phet-finish/all-report-bound.json \
  --output catalog/acquisition/phet-browser-evidence.json
```

Browser viewport checks do not certify physical phones or tablets. Physical-device certification remains pending, and these new files do not change the catalog's PhET readiness status or replace the earlier acquisition evidence.

The pending [required-screen coverage manifest](../catalog/acquisition/phet-required-screen-coverage.json) now separates content gaps from device certification. Saved home-screen evidence names 22 screens across eight simulations; 14 additional screens have no recorded interaction/reset sample. The other eight simulations still need a screen inventory from their pinned files. Existing reports also omit explicit selected-screen identity, so the successful first-screen mapping remains an inference from the reviewed entry action. No simulation has complete substantive teaching-content review recorded.

The runner accepts one entry sequence per unique simulation ID in a manifest. Reuse it with separate bounded per-screen manifests and reports, preserving the original source ID and hash, then bind each report to the intended screen. Current desktop and phone-width passes remain valid sample evidence. Actual phone/tablet local-file opening and touch usability remain a separate physical-device requirement. This coverage inventory used saved reports and screenshots only; it fetched no bodies and ran no browser checks.
