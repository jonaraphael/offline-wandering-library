# Reusable offline document checks

Create a small JSON manifest recording each local HTML file's exact SHA-256, expected image/table counts, and any explicitly absent companion PDFs:

```json
{"assets":[{"id":"food","destination":"food.html","sha256":"REPLACE_WITH_WHOLE_FILE_SHA256","expected_images":4,"expected_tables":9,"allow_missing_local":["companion.pdf"]}],"viewports":[{"width":1280,"height":900},{"width":390,"height":844}]}
```

```sh
node scripts/check_documents.cjs --manifest checks.json --root rendered \
  --output evidence/report.json --screenshots evidence \
  --playwright /path/to/playwright-core --browser /path/to/chromium
```

The command reuses the portable PhET QA script's bounded argument, viewport, path and source-integrity validation. It uses existing Node.js 18+, Playwright and Chromium; no dependencies or content are downloaded. Installed modules and browser binaries can use their normal defaults instead of explicit paths.

Each document opens through `file://` with networking blocked. Checks cover loaded illustrations, expected tables, same-page anchors, missing local companion links, horizontal page overflow, console/runtime errors, attempted network requests and unchanged source bytes. Screenshots capture the beginning and representative table/figure at each viewport.

`allow_missing_local` contains exact HTML `href` strings, never patterns. These links remain visible in `pending_local_links`, and the report sets `companion_files_complete:false`; passing a staged HTML rendering check does not certify an assembled library. Remove exceptions for finished-library acceptance. Cross-document fragment targets are not verified by this checker. Detailed evidence stays in JSON, while stdout is a short summary.
