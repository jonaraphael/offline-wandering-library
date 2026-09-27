#!/usr/bin/env python3
"""Reproducible offline browser QA using synthetic media only; no downloads."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.lessons import render
from owl.safety import atomic_write, reject_symlinks, safe_path, sha256_file


BROWSER_CHECK = r"""
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const options = JSON.parse(process.argv[1]);
let playwright;
try { playwright = require(options.playwright || 'playwright'); }
catch {
  try { if (options.playwright) throw Error(); playwright = require('playwright-core'); }
  catch { throw Error('Supply --playwright /path/to/playwright-core and --browser /path/to/already-installed/chromium; no dependencies were downloaded.'); }
}
(async () => {
  const report = {schema_version: 1, synthetic_only: true, downloads: false,
    network_blocked: true, physical_device_certification: 'pending', checks: []};
  const browser = await playwright.chromium.launch({headless: true,
    chromiumSandbox: true, executablePath: options.browser || undefined});
  report.browser_version = browser.version();
  try {
    for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
      const context = await browser.newContext({viewport, offline: true, permissions: []});
      const check = {viewport, remote_request_count: 0, errors: []};
      await context.route(/^https?:/, async route => {
        check.remote_request_count++;
        await route.abort();
      });
      const page = await context.newPage();
      page.on('console', message => {
        if (message.type() === 'error' && check.errors.length < 20) check.errors.push(message.text().slice(0, 500));
      });
      page.on('pageerror', error => { if (check.errors.length < 20) check.errors.push(error.message.slice(0, 500)); });
      try {
        await page.goto(pathToFileURL(path.join(options.output, 'lesson.html')).href, {timeout: 15000});
        await page.locator('audio').click({timeout: 5000});
        await page.evaluate(async () => {
          const audio = document.querySelector('audio');
          audio.muted = true;
          await audio.play();
        });
        await page.waitForFunction(() => {
          const audio = document.querySelector('audio');
          return audio.currentTime > 0.1 && document.querySelector('track').readyState === 2;
        }, null, {timeout: 10000});
        check.media = await page.evaluate(() => {
          const audio = document.querySelector('audio');
          return {duration_seconds: audio.duration, playback_seconds: audio.currentTime,
            media_error: audio.error?.message || null,
            track_state: document.querySelector('track').readyState,
            caption_cues: audio.textTracks[0]?.cues?.length || 0,
            transcript_present: document.querySelector('details pre').textContent.includes('Synthetic complete caption.'),
            viewport_width: innerWidth, document_width: document.documentElement.scrollWidth};
        });
        await page.screenshot({path: path.join(options.output, `lesson-${viewport.width}.png`)});
        check.success = check.media.duration_seconds === 2 && check.media.playback_seconds > 0.1 &&
          !check.media.media_error && check.media.track_state === 2 && check.media.caption_cues === 1 &&
          check.media.transcript_present && check.media.document_width <= viewport.width + 1 &&
          check.remote_request_count === 0 && check.errors.length === 0;
        if (!check.success) check.failure = 'Media, captions, transcript, layout or offline checks failed';
      } catch (error) { check.success = false; check.failure = error.message.slice(0, 1000); }
      finally { await context.close(); }
      report.checks.push(check);
    }
  } finally { await browser.close(); }
  report.success = report.checks.every(check => check.success);
  const reportPath = path.join(options.output, 'report.json');
  fs.writeFileSync(reportPath + '.part', JSON.stringify(report, null, 2) + '\n');
  fs.renameSync(reportPath + '.part', reportPath);
  process.stdout.write(JSON.stringify({success: report.success, synthetic_only: true,
    checks: report.checks.map(check => ({width: check.viewport.width, success: check.success,
      failure: check.failure?.slice(0, 180)})), report: reportPath}) + '\n');
  if (!report.success) process.exitCode = 1;
})().catch(error => { console.error(error.message.slice(0, 1600)); process.exitCode = 1; });
"""


def create_fixture(output: Path) -> None:
    """Generate a two-second silent WAV and one VTT cue, then use the real adapter."""
    output = output.resolve()
    reject_symlinks(output)
    marker = safe_path(output, "qa_owner.json")
    owner = {"owner": "owl-synthetic-lesson-browser-qa", "version": 1}
    if output.exists():
        if (not marker.is_file() or marker.stat().st_size > 4096 or
                json.loads(marker.read_text(encoding="utf-8")) != owner):
            raise ValueError("Output directory lacks the synthetic QA ownership marker; choose a new directory")
    else:
        atomic_write(marker, (json.dumps(owner, sort_keys=True) + "\n").encode())
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 16000)
    atomic_write(safe_path(output, "media.wav"), buffer.getvalue())
    atomic_write(safe_path(output, "captions.vtt"), b"WEBVTT\n\n00:00.000 --> 00:02.000\nSynthetic complete caption.\n")
    assets, sources = {}, {}
    for identity, name in (("media", "media.wav"), ("captions", "captions.vtt")):
        source = safe_path(output, name)
        sources[identity] = source
        assets[identity] = {"id": identity, "destination": name,
                            "size_bytes": source.stat().st_size, "sha256": sha256_file(source)}
    assets["lesson"] = {"id": "lesson", "title": "Synthetic ordinary-file lesson",
                        "destination": "lesson.html", "generation": {"recipe_id": "lesson_qa", "lesson_id": "synthetic"}}
    recipe = {"id": "lesson_qa", "source_asset_ids": ["media", "captions"],
              "selection": {"reviewed": True, "lessons": [{
                  "id": "synthetic", "title": "Synthetic ordinary-file lesson", "course_id": "test",
                  "source_url": "https://example.invalid/lesson", "license": "CC0",
                  "attribution": "Synthetic QA fixture", "language": "en", "kind": "audio",
                  "content_html": "<p>Synthetic fixture; no publisher content. The original local media, native caption track and timed transcript should all work without a server.</p>",
                  "media": [{"asset_id": "media", "mime_type": "audio/wav", "captions": [
                      {"asset_id": "captions", "language": "en", "label": "English"}]}],
              }]}}
    render(recipe, sources, assets, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(".owl/acquisition/lesson-qa"), help="Owned synthetic fixture/report directory")
    parser.add_argument("--node", default=shutil.which("node"), help="Existing Node.js >=18 executable")
    parser.add_argument("--playwright", help="Existing Playwright or playwright-core module directory")
    parser.add_argument("--browser", help="Existing Chromium/Chrome executable; otherwise Playwright's installed browser")
    args = parser.parse_args(argv)
    if not args.node:
        parser.error("Node.js is required; supply --node /path/to/node. This script never installs dependencies.")
    output = args.output_dir.resolve()
    try:
        create_fixture(output)
        options = {"output": str(output), "browser": args.browser, "playwright": args.playwright}
        result = subprocess.run([args.node, "-e", BROWSER_CHECK, json.dumps(options)],
                                capture_output=True, text=True, timeout=60)
        if result.stdout:
            print(result.stdout[:2048], end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr[:1800], file=sys.stderr)
        return result.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error)[:1800], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
