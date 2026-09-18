# Initial validation evidence

The initial implementation was exercised on macOS/Apple Silicon with Python
3.12, Node.js 20, and the versions in `requirements-tested.txt`. The source audit
was performed on 2026-09-18 UTC. This document records evidence, not a claim that
all target hardware or the largest profiles have been tested.

- The automated suite covers catalog validation, decimal capacity/headroom,
  traversal/symlink/reparse-point rejection, streaming checksums, interrupted
  transfers, real loopback HTTP Range responses, ignored ranges, changed entity
  validators, hash failures, cache reuse, incomplete builds, repeated builds,
  static links, extraction and the JavaScript search engine.
- Real PDF, EPUB and tiny generated ZIM fixtures test the extraction paths.
  Node executes the exact script embedded in `SEARCH.html`, including ranking,
  snippets, Unicode, multi-block common-word postings and damaged index handling.
- The three-file demo was built through the CLI and independently verified.
- A live HTTPS build downloaded the pinned EPA water-disinfection PDF and
  successfully created and verified its navigation, full-text index and metadata.
- All 20 initial critical PDFs were downloaded from their catalog sources for
  the source audit, then hash-checked and assembled through the builder. Their
  152,460,333 source bytes produced 2,745 passages and a 14,127,290-byte search
  index. Seven assets reported some pages without extractable text. Such pages
  may be blank or image-based; OWL reports partial coverage rather than assuming
  OCR. No critical asset was entirely metadata-only.
- The four reader distributions were downloaded, sized and SHA-256-hashed;
  upstream MD5 sidecars were additionally compared. No downloaded reader was
  executed. Large ZIM sizes and SHA-256 pins were checked against upstream
  Metalink files; the large archives were not downloaded for this validation.

No physical exFAT SSD, iPhone/Pixel file picker, Raspberry Pi reader, or complete
512 GB/1 TB build was exercised. The available automated browser rejects local
`file://` navigation, so an actual local-browser UI smoke test could not be run.
No browser-policy workaround was attempted. Search-engine tests do not establish
external-drive browser permissions or phone storage-provider compatibility.

The workflow in `.github/workflows/test.yml` defines Windows/macOS/Linux Python
3.11/3.13 tests and a separate Linux ZIM job; defining this workflow is not evidence
of a hosted CI run. Before relying on a drive, run the verifier and the device
checks in `docs/usage.md`, offline, on each intended device. Keep a separately
stored verified backup.
