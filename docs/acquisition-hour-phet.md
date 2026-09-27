# PhET: build-time source pins and desktop checks

Fourteen additional original, regular English HTML5 simulations are pinned in
[`catalog/acquisition/hour-phet.yaml`](../catalog/acquisition/hour-phet.yaml), bringing
the collection to 16. Each has an exact-version HTTPS URL, whole-file SHA-256 and
byte count. Publisher runtimes, embedded assets, attribution and CC BY-NC 4.0 notices
are retained. No Java, Flash or PhET-iO files are included.

The original files were downloaded to temporary storage before the user clarified
that content acquisition should wait for a build. Further downloads stopped. The
checks below use those existing temporary files only; no library build or SSD copy
was performed. Public catalog entries depend only on their HTTPS sources.

All 16 cold-launched from `file://` in macOS Chrome 153.0.8010.48
with the network disabled and HTTP/HTTPS requests blocked. Each passed one
representative first-screen interaction that changed simulation state, followed by
Reset All restoring that state. Optional analytics/update requests failed as
expected without preventing the checked activity. The originals were not modified
to suppress those requests.

| Simulation | Version | Interaction |
| --- | --- | --- |
| Ohm’s Law | 1.4.31 | keyboard: slider ArrowRight |
| Circuit Construction Kit: DC | 1.5.2 | keyboard: checkbox Space |
| Forces and Motion: Basics | 2.6.5 | keyboard: checkbox Space |
| Energy Skate Park: Basics | 1.5.1 | keyboard: slider ArrowRight |
| Projectile Motion | 1.0.34 | drag initial speed slider |
| Pendulum Lab | 1.0.35 | drag pendulum length slider |
| Wave on a String | 1.2.4 | keyboard: slider ArrowRight |
| Gravity Force Lab: Basics | 1.1.27 | keyboard: slider ArrowRight |
| Bending Light | 1.2.5 | mouse: laser power |
| States of Matter: Basics | 1.2.23 | choose Gas |
| Build an Atom | 1.9.3 | drag proton into atom |
| Balancing Chemical Equations | 2.1.2 | coefficient slider ArrowUp |
| pH Scale: Basics | 1.7.5 | hold dropper button |
| Natural Selection | 1.5.15 | mouse: Add a Mate |
| Fractions: Intro | 1.0.33 | mouse: numerator increase |
| Area Builder | 1.1.38 | mouse: dimensions checkbox |

[Machine-readable observations](acquisition-hour-phet-checks.json) record source
hashes and before/after/reset values. Initial harness checks missed some older
runtime property paths and attempted clicks on sliders requiring drags; corrected
checks verified those interactions using the same source files. Every simulation
also ran for at least 600 animation frames in its original cold-launch check with
no uncaught page error.

**PhET remains partial.** These are desktop sample checks, not exhaustive checks of
every screen, learning activity, accessibility behavior, or intended mobile device.
The library's existing navigation will link the ordinary HTML files when built.
A future build downloads only selected pinned sources and rejects changed bytes.
Completing the declared device requirement needs actual target devices; desktop
emulation would not establish iPhone local-file support.
