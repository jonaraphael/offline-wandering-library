# OpenSSH portable 10.5p1 source-pinned manual edition

The complete portable 10.5p1 edition closes the missing `ssh-keygen`, `sftp-server`, `ssh-keyscan` and `ssh-keysign` manual coverage. It contains all 16 ordinary manuals in the preserved publisher archive, including `ssh-copy-id`, the two helper manuals and `moduli`. Each HTML manual links to its unmodified roff source, the release `LICENCE`, and the complete source archive. The edition is explicitly labeled **OpenSSH portable 10.5p1**, including the platform-specific configuration caveat.

The larger presets replace the eight incomplete OpenBSD 7.9 default manuals and their separate portable-release license companion with this complete edition. Earlier assets remain in the catalog as optional records. The fixed 16 GB and 64 GB presets do not change. Programming remains partial because selected documentation still references system/platform manuals outside its declared scopes; physical-device validation is also separate.

The source archive was captured on September 18, 2026 and rehashed locally on September 22. Its pin is 2,333,659 bytes and SHA-256 `d44d28a839ea9daf969cc69150fde59910b2b39361dad81a3bd6cbd19218db11`. No new content body was downloaded. The 33 generated outputs total 928,907 bytes: 16 HTML manuals, 16 original roff files and one release notice. Supporting sources/notices are excluded from readable-document totals. The build also reserves 1 MiB for rendering scratch, the normal receipt allowance, and regeneration output staging.

## Reproduce and review

`scripts/prepare_openssh.py` consumes the preserved archive, captured prior rendered manuals, and their manifest. It rechecks the admitted source pin, discovers exactly the reviewed 16 archive members, renders them, compares all 15 previously rendered manual bodies, and writes the accepted fragment plus a local preview. The `ssh-copy-id` manual is rendered from its verified original source for the first time. This command has no HTTP implementation.

```sh
python scripts/prepare_openssh.py PATH_TO_EXISTING_PROGRAMMING_EVIDENCE .owl/acquisition/openssh-review
python scripts/acquire_content.py stage \
  --fragment .owl/acquisition/openssh-review/fragment.json \
  --output .owl/acquisition/openssh-candidate \
  --resource linux-programming-docs --profile full-1tb
node scripts/check_manuals.cjs \
  --fragment .owl/acquisition/openssh-review/fragment.json \
  --root .owl/acquisition/openssh-review/preview \
  --output .owl/acquisition/openssh-review/browser-evidence.json
```

The browser checker accepts `--playwright`, `--browser` and `--screenshots` to use already installed tools. It never installs a browser or accesses a content server. Browser evidence is committed separately from the local source bodies and screenshots.

## Generation contract

The normal build downloads only the existing pinned archive when this edition is selected. Before any acquisition, it requires `mandoc` on `PATH` and compares its stable HTML probe with the frozen renderer fingerprint. Plans do not require the renderer. Different renderer output stops the build with instructions to review a new recipe. All generated files must match their accepted whole-file hashes before publication, so a matching probe alone cannot make changed output acceptable.

The `mdoc` adapter uses no shell, executes no source code, and extracts no arbitrary archive paths. It rejects changed source/member hashes, archive traversal, duplicate members, links, nonregular selected members and external-file/command roff directives. Bounds are 10,000 archive members, 64 MiB compressed input and decompressed TAR stream, 1 MiB per selected source, 100 manuals, 10 seconds per renderer call, 4 MiB stdout and 8 KiB stderr. A bounded decompressed reader sits before the TAR parser, so PAX and GNU extension metadata cannot bypass the 64 MiB limit. Plain and gzip TAR inputs are supported. Interrupted processes are terminated and normal build checkpoints retain verified originals for retry.

The HTML keeps the complete rendered manual body. Six source `.Sx` section references that mandoc emitted as broken same-page anchors are explicitly rebound to the named section in another selected manual. The recipe pins each target and occurrence count: three `TIME FORMATS`, two `VERIFYING HOST KEYS`, and one `PATTERNS` reference. Other references within the complete release use ordinary local links. Names of external system manuals remain visible and are listed at the bottom of each page; unavailable destinations are not emitted as broken local links. There are 35 distinct outside-release manual references, including optional/platform-specific `ssh-askpass`, `xauth`, `login.conf`, `tun`, `ipsecctl`, and C-library/system-call references.

## Recorded validation

- Twelve focused adapter tests pass, including a real local mandoc render, deterministic rerendering, retained text/notices, changed source/probe rejection, unsafe archive/duplicate rejection, oversized PAX/GNU metadata, bounded renderer output and unsupported source directives. Build tests also verify that plans require no renderer, and missing or changed renderers stop before downloads or target mutation.
- All 15 previously captured manual bodies have identical normalized text and table counts after transformation; the additional `ssh-copy-id` body comes from the matching original source.
- All 16 pages pass offline Chromium checks at 1280 px and 390 px: 32 checks, no network requests, JavaScript errors, broken local files, broken same-page anchors, missing images or horizontal page overflow.
- Desktop and phone screenshots of the formerly missing manuals were reviewed. The phone synopsis preserves command names as whole tokens and wraps arguments without clipping.
- The staged candidate validates navigation and all five profile plans. It preserves the fixed small selections and leaves larger-profile content shortfalls and unrelated reviews explicit.
- A bounded normal-build check using the existing local archive and these 33 outputs completed with 83 verified files, zero missing files and zero checksum failures. A second build succeeded with download and rendering functions disabled, proving reuse of the verified originals and generated outputs. This check downloaded no new bodies and did not touch a production drive.

Portable records: [accepted recipe and output pins](../catalog/acquisition/openssh-portable.yaml), [source/body evidence](../catalog/acquisition/openssh-portable-evidence.json), and [offline browser checks](../catalog/acquisition/openssh-portable-browser-evidence.json).
