# Sync: the OWL experience

Status: design spec, 22 November 2026. It replaces the stepper-and-planner
builder page and the tabbed start page. Reference mockups for every screen in
this document are in [`sync/`](sync/): open
[`builder-reference.html`](sync/builder-reference.html) and
[`reader-reference.html`](sync/reader-reference.html) in a browser and use the
selector in the corner to move between states.

## 1. The idea

An OWL drive is an appliance, like an iPod. The hosted page shows one drive
and one verb, **Sync**. The first build, a resumed build and a later update
are the same button. Curation exists, on a second screen that most people
never open.

The drive opens to a reader that behaves like a phone app: a home screen,
search, saved items and help.

Two people use OWL and they differ.

| | Builder | Reader |
|---|---|---|
| Who | Prepares the drive. Comfortable installing a browser and plugging in a drive. | Whoever holds the drive later. May never have used a file manager. May be under stress. |
| Where | Chrome, Edge or Arc on a computer, online | Any computer, Android phone or iPhone, offline |
| Wants | A finished drive | An answer |
| Sees | `index.html` on GitHub Pages | `START_HERE.html` on the drive |

## 2. Rules for both surfaces

1. **One primary action per screen.** Every other control is a text link or
   sits one level down.
2. **Defaults decide.** A person who presses only the primary button gets
   the recommended result. No question blocks the primary button unless OWL
   cannot work without the answer.
3. **Nothing is removed, only moved down.** Every capability of the current
   builder (per-collection and per-file selection, editions, search, bulk
   include and exclude, split archives for FAT32, verify and repair,
   diagnostics) stays reachable from Manage or Advanced.
4. **A disabled or missing control says why** in the status line next to it.
5. **Plain words.** Collections use the titles and blurbs in
   `src/owl/collection_copy.json`. The words *ZIM*, *asset*, *manifest*,
   *tier*, *shard* and *catalog* do not appear outside Advanced and
   diagnostics.
6. **State is honest.** The page claims only what it measured. It does not
   show a drive brand, a total capacity or a time estimate it has not
   measured.
7. **The same eight categories, names and colours** appear in the builder's
   storage bar, in Manage and on the reader's home screen (section 6).
8. Light and dark themes, keyboard operation and screen-reader labels are
   part of the definition of done (section 7).

## 3. Words

| Word | Meaning |
|---|---|
| Drive | The folder the builder picked, normally the top of a USB drive or SD card. Its name is the folder name the browser reports. |
| Library | Everything OWL keeps on the drive: `START_HERE.html`, `LIBRARY/` and the reader apps. |
| Recommended library | The planner's default for the space available. |
| Sync | Make the drive match the chosen library: download what is missing, verify it, remove what was dropped, rebuild the index and reader. |
| Category | One of the eight groups in section 6. |

## 4. Builder (`index.html` on GitHub Pages)

### 4.1 Layout

One screen, no page scroll at 1280 × 720 in any state except Manage.

- **Top bar.** Owl mark and "Offline Wandering Library" at left. "How it
  works" at right opens a short sheet (what OWL is, what Sync does, what is
  needed: Chrome, Edge or Arc on a computer; a drive with 16 GB to 1 TB
  free; an internet connection for the download). The sheet also links to
  the command-line builder.
- **Stage**, centred: the drive inside a progress ring, a title, a status
  line, the storage bar with its legend, the primary button, one secondary
  link.
- **Rail**, bottom: three steps, `Choose drive · Sync · Read`, with the
  current step marked. It contains no controls.

The ring, title, status line, bar and button are the same elements in every
state. Only their contents change, so the page never jumps.

### 4.2 States

| State | When | Ring and drive | Title | Status line | Bar | Primary | Secondary |
|---|---|---|---|---|---|---|---|
| `empty` | First visit, supported browser | Empty ring, drive outlined | Plug in a drive | Any USB drive or SD card with 16 GB to 1 TB free. Files already on it stay. | Hidden | **Choose drive** | See what goes on a drive |
| `remembered` | A drive was used before in this browser | Empty ring, drive dimmed | *drive name* | Last synced *date*. | Last known bar, dimmed | **Reconnect** *drive name* | Use a different drive |
| `measuring` | After a drive is picked | Rotating arc | *drive name* | Measuring free space… | Skeleton | None | Choose a different drive |
| `needs-size` | Free space cannot be measured | Empty ring | *drive name* | How much space does this drive have? Use the number printed on it. | Size chips 16, 32, 64, 128, 256, 512 GB, 1 TB | None; choosing a chip continues | Choose a different drive |
| `ready` | New drive, plan computed | Ring track, green light | *drive name* | *59.6 GB free.* The recommended library uses *58.2 GB*: *412* books, manuals and courses. | Categories plus free | **Sync** | Manage what goes on it |
| `behind` | OWL drive with work to do | Arc at the fraction already on the drive | *drive name* | One of: *Unfinished: 21 GB to go.* / *3 updates: adds 1.1 GB, removes 0.3 GB.* / *Your changes: adds 6.4 GB, removes 3.1 GB.* | On-drive part solid, pending part pale | **Sync** | Manage what goes on it |
| `current` | OWL drive that matches its library | Full ring, check mark | Up to date | Synced *14 March 2026*. *412* items, *58.2 GB*. | Solid | None | Manage what goes on it · Check every file |
| `syncing` | Sync running | Arc = bytes written ÷ bytes planned; light pulses | *42%* | *24.4 of 58.2 GB · about 1 h 10 min left* then, on a second line, *Now: WikiMed medical encyclopedia* | Synced part solid, rest pale | **Pause** | None |
| `finishing` | Downloads done, index and reader being written | Full arc, pulsing | Finishing | Building the search index and the start page. | Solid | None | None |
| `paused` | Paused, or the tab was reopened mid-sync | Arc stopped, amber | Paused at *42%* | Nothing is lost. Sync continues where it stopped. | As `behind` | **Sync** | Manage what goes on it |
| `waiting` | Network dropped during sync | Arc stopped, amber | *42%* | Waiting for the internet. Sync continues by itself. | As `syncing` | **Pause** | None |
| `done` | Sync finished | Full green ring, check mark | Ready | Open your library on *drive name*. | Solid | **Try it** | Check every file · Sync another drive |
| `done-gaps` | Finished, some items failed | Full amber ring | Ready, with *3* items missing | The library works. *3* items could not be downloaded. | Solid, gap marked | **Try those again** | Show the 3 items · Sync another drive |
| `problem` | Drive unplugged, read-only, full, permission refused | Red arc | One plain sentence naming the problem | One sentence saying what to do. "Nothing is lost" when true. | Last known | The fix: **Reconnect**, **Choose another drive** or **Sync** | Technical details |
| `too-small` | Free space below the smallest plan | Empty ring | Not enough room | OWL needs at least *N GB* free. This drive has *M GB*. | Hidden | **Choose another drive** | None |
| `unsupported` | Safari, Firefox, any phone | Drive outlined | Open this page in Chrome, Edge or Arc on a computer | Those browsers can write straight to a drive. This one cannot. | Hidden | **Copy link** | See what goes on a drive · Build with the command line |

Notes on states:

- **The folder dialog.** The page cannot see a drive until the builder picks
  it once. "Choose drive" opens the browser's folder dialog; the `empty`
  status line gains "In the window that opens, click the drive's name, then
  Open" while the dialog is up. After the first pick the page remembers the
  drive, and a later visit starts in `remembered`, or directly in `ready`,
  `behind` or `current` when the browser still holds permission.
- **Drive name** is the picked folder's name. When the browser reports an
  empty name the title is "Your drive".
- **Time estimates** appear after 30 seconds of transfer and come from the
  measured rate. Before that the second half of the status line is absent.
- **During `syncing`** a card below the stage reads "Keep this tab open and
  the drive plugged in. You can use the computer for other things." After
  20 seconds it is joined by the phone card: the Kiwix QR code for iPhone
  ("Install it now, while you are online") and one line for Android and
  computers ("The reader app is copied onto the drive").
- **Try it** opens the drive's `START_HERE.html` in a new tab. If the browser
  cannot open the preview, the status gives the file name and drive.
- **`current` has no primary button.** A disabled Sync button reads as a
  fault.
- The computer is kept awake during `syncing` where the browser allows it
  (the existing wake lock).

### 4.3 What Sync does

Sync is one operation, *reconcile*, in place of today's separate start and
resume paths.

1. **Read the drive.** No library: the drive is new. A browser build record
   (`LIBRARY/.owl/browser-build.json`, any earlier version): load it. A
   library with no browser record (made by the command-line builder): treat
   its files as unverified candidates.
2. **Decide the target.** The target is the builder's saved choice applied
   to today's published catalog and to the space available (free space plus
   the bytes OWL already holds). A new drive's choice is "recommended". The
   choice is stored on the drive (step 6), so any computer syncs the same
   drive the same way.
3. **Compare.** Each target item is *present* (recorded and verified, or
   found on the drive with matching size and SHA-256), *missing* or
   *changed*. Each recorded item that is no longer a target is *dropped*.
   The status line reports the totals before anything is written.
4. **Add first.** Download and verify missing and changed items in priority
   order, most essential first. A changed item's old copy stays until its
   replacement verifies. When the drive lacks room for both copies, the
   update is held back and listed in Manage with a "Replace in place" action;
   it is not applied silently.
5. **Remove last.** Delete dropped items and replaced copies after all
   additions verify.
6. **Finish.** Rebuild the search index, the reader and the reader data.
   Write the record: the choice, the catalog version, the date, every item
   with its hash.

Safety rules:

- Sync deletes only files listed in the drive's own record. A file OWL did
  not write is never deleted, moved or overwritten, inside or outside
  `LIBRARY/`.
- Stopping at any moment (Pause, closed tab, pulled drive, lost network)
  loses at most the piece being written. The next Sync continues.
- A catalog change between two sessions never produces an error. Today's
  "pinned selection has changed" stop is replaced by step 3.
- Interrupted mid-update, the drive still opens: the reader on the drive
  describes the last finished sync until the next one finishes.
- "Check every file" re-hashes every item and re-downloads the ones that
  fail. It is reconcile with nothing trusted.

Space: the planner fills the available space as it does today, including the
reserve for the index and readers. On a FAT32 drive (detected while
measuring, as today) large files are written in parts; the control for this
sits in Manage under Advanced with the detected value preselected.

### 4.4 Manage

Opened from "Manage what goes on it". It replaces the stage; the top bar
shows "‹ *drive name*" to go back. Nothing is written to the drive from this
screen.

- **Summary, pinned to the top:** the storage bar, "*58.2* of *59.6 GB*",
  and "Reset to recommended" when the choice differs from the default.
- **Space for the library**, when a drive is connected: a slider at the top
  of the summary that sets how much of the drive OWL may use. The summary bar
  spans the drive's available space and the slider's handle sits on it at the
  limit. Left of the handle is the library by category, then any budget not
  yet used; right of it is hatched and labelled "*831 GB* stays free".
  - **Stops.** 1, 8, 16, 32 and 64 GB, then every 32 GB up to 992 GB, then
    1 TB. Stops above the drive's available space are dropped and the last
    stop is all of it (at most 1 TB). A stop the planner cannot fill is not
    offered. The handle snaps to the nearest stop.
  - **Live.** While the handle moves, the recommended library, the bar, the
    totals line and every category's size update at each stop. Nothing is
    read from the drive or the network during a drag.
  - **Default** is all available space, shown as "All *59.6 GB*". When the
    limit is lower, the value reads "*128 GB*" with a link "Use all *959 GB*".
  - **Keyboard.** Left and Right move one stop, Page Up and Page Down five,
    Home and End to the ends. The slider's value text is "*128 GB* of
    *959 GB*".
  - **Kept.** The limit is stored on the drive with the choice, so a later
    sync on any computer keeps it. "Reset to recommended" restores the
    default library for the current limit and leaves the limit alone.
  - **With custom choices.** Switches the builder set stay as set when the
    limit moves. If they no longer fit, the summary shows the overflow and
    "Make it fit".
  - **Lowering it below what the drive already holds** produces `behind`
    with "Your changes: removes …" after Done, like any other change.
  - **Below 16 GB** the library is the 16 GB library reduced in priority
    order: the least essential items leave first and the essentials last.
    Reader apps are included only when the library contains an encyclopedia
    file.
  - On the stage, a limited drive's status line reads "*959 GB* free, limited
    to *128 GB*." before the description of the library, and the bar's total
    stays the drive's available space.
- **Search field:** "Find a collection". Typing filters the list and opens
  matching categories.
- **Eight category rows:** colour dot, name, one-line description, size on
  the drive, chevron. A category opens to its collections.
- **Collection row:** switch, plain title, one-line blurb, size. A
  collection with several editions shows them as a choice beneath the title
  with the recommended one marked. "Choose files" opens the per-file list.
  The planner's must-have items carry an "Essential" label and can still be
  switched off.
- **Over capacity:** the bar's overflow turns red and the summary reads
  "*3.1 GB* over." with a "Make it fit" button that removes the least
  essential items until the library fits. The back link stays enabled; an
  over-capacity choice cannot be synced and the stage says so.
- **Advanced**, collapsed at the bottom: split large files for FAT32,
  bulk include and exclude for the filtered list, the storage accounting
  table, diagnostics.
- **Done** returns to the stage. If the choice changed, the state is
  `behind` with "Your changes: adds …, removes …".

Without a drive ("See what goes on a drive"), Manage opens with size chips
above the summary, 64 GB preselected, and no Done button. This is also the
page's behaviour in unsupported browsers.

### 4.5 `SELECT.html`

The offline planner stays one generated file from the same template. It is
Manage without a drive (size chips, summary, list) followed by the
command-line section that exists today. Its look matches the hosted page.

### 4.6 Removed from the page

The three-step stepper, the "Review your library" page section, the Customize
toggle, the separate Resume and Verify buttons, the build and done page
sections, the mobile summary bar. Their functions live in the states above.

## 5. Reader (`START_HERE.html` on the drive)

### 5.1 Constraints

- The reader runs from `file://` with no server. `fetch` of local files does
  not work there; data loads through `<script>` files.
- Some viewers show the HTML without running scripts or following links
  (a phone's file preview). `docs/device-matrix.md` lists the iPhone test as
  pending. The reader therefore has two layers: a static page that is
  complete by itself, and the app, which appears only after its script has
  run from the drive (the existing `live` class).
- Every generated file is produced identically by the browser builder and
  the Python builder; the parity test covers the reader.

### 5.2 The app

One page with four tabs. On a phone the tab bar is at the bottom; from
900 px wide it is at the top. Views are addressed by the URL fragment, so the
browser's Back button works and a view can be bookmarked.

**Home** (`#/`)

1. Title "Library", with "Works without internet" beneath it.
2. Search field. Focusing it opens the Search tab.
3. **Urgent:** the emergency tasks from `offline-layout.json` as red chips.
   A chip opens its document directly.
4. **Recently opened:** up to three items, shown once something has been
   opened on this device.
5. **Categories:** eight tiles with icon, name and item count, in the
   colours of section 6. A category with nothing on this drive is absent.
6. "Everything, A to Z".

**Category** (`#/c/<id>`): back link, title, then one row per book or
document. A book published as chapter files is one row that opens to its
chapters (`book_chapters`). Each row has a title, a kind ("PDF", "Book, 30
chapters", "Course", "Encyclopedia, opens in Kiwix"), a size and a star.
Subject chips from the topic atlas filter the list when the category has
more than 30 rows.

**Opening things.** A document opens in the same tab; Back returns to the
same place in the list. An encyclopedia file opens a sheet instead of a dead
link: three numbered steps for this device (where the Kiwix app is, how to
open the file with it) and the file's location on the drive.

**Search** (`#/search`): the existing search engine and index, in this
view. Before a query: six example searches. Results: one card per document
with the best passage, the searched words marked, other matching places in
the same document, and "Open". A result inside an encyclopedia file says
which article to look up in Kiwix. Options (limit to a category) sit behind
"Options".

**Saved** (`#/saved`): starred items, then everything opened recently. The
empty state shows a star and one sentence. Saved items are kept in the
browser on this device, and the view says so. Where browser storage is
unavailable the stars and this tab are absent.

**Help** (`#/help`): "Opening files on this *iPhone / Android phone /
Windows PC / Mac*", detected, with a way to switch device; the reader apps on
the drive; "About this drive" (synced date, size, item count, items that
could not be downloaded, link to the full file list and build report); how to
make another drive.

### 5.3 The static page

With scripts off, `START_HERE.html` shows, in order: the title; one
sentence, "Files on this drive are in the LIBRARY folder, grouped by
subject"; the urgent tasks, each with its file's location on the drive; the
eight categories, each listing its books and documents with their locations
(chapters of a book are not listed one by one); help for each kind of device.
The tab bar, search field and stars are absent. When the app starts, the
static page is replaced.

### 5.4 Pages that go away

`LIBRARY/INDEX/` keeps data, not pages: the per-view HTML files (categories,
critical, topics, books, sections, letters) are replaced by views of the app.
`SEARCH.html` remains as a one-line redirect to `START_HERE.html#/search`.
The build report and inventory remain as plain files linked from Help.

## 6. Categories

| Id | Name | Light | Dark |
|---|---|---|---|
| `health` | Health | `#2a78d6` | `#3987e5` |
| `food` | Food and farming | `#eb6834` | `#d95926` |
| `shelter` | Water, shelter and safety | `#1baf7a` | `#199e70` |
| `trades` | Repair and trades | `#eda100` | `#c98500` |
| `school` | School | `#e87ba4` | `#d55181` |
| `reference` | Encyclopedias and maps | `#008300` | `#0ca30c` |
| `advanced` | College and technical | `#6250d6` | `#9085e9` |
| `culture` | Stories and culture | `#e34948` | `#e66767` |

Reader apps and anything unassigned count toward the totals and are drawn in
neutral grey. Free space is the track colour. The bar keeps a 2 px gap
between segments and always has its legend; colour is never the only label.

`src/owl/categories.json` holds the ids, names, descriptions, colours and icon
paths; the builder and both reader generators read it. A collection's
category is the builder's existing rule: the `theme` in
`collection_copy.json` when present, otherwise the vertical of its primary
topic in `topic_verticals.json`. The reader draws the `trades` and `school` icons in the darker tints
of `sync/reader.css` so that they keep 3:1 contrast on white.

## 7. Look and behaviour

The reference files are the visual source of truth; `sync/builder.css` and
`sync/reader.css` are written to be used as the production styles.

- System font stack. One accent colour (`#0b6bcb`, light text on it passes
  WCAG AA). Neutral surfaces. Red is reserved for Urgent and for problems,
  amber for paused and partial, green for done.
- Motion: the ring animates progress, views cross-fade in 150 ms, and
  `prefers-reduced-motion` removes both.
- Targets are at least 44 × 44 px on touch screens. Every control is
  reachable by keyboard in visual order with a visible focus ring. The ring
  is a `progressbar` with a text value; state changes are announced through
  one polite live region.
- No horizontal scrolling at 320 px and wider.
- The reader's body text is 17 px on phones.

## 8. Acceptance

Automated, run by the chair with the harness in
`/Users/jonathanraphael/git/owl-council-reports/ui-harness/`:

1. `python -m unittest discover -s tests`, every `tests/*.test.mjs` and
   `tests/**/*.test.cjs`, the plan sweep and `build_selector.py --check`
   pass.
2. **First sync.** Headless Chromium, folder dialog replaced by a private
   browser folder, local server for sources: `empty` → Choose drive →
   `measuring` → `ready` → Sync → `syncing` → `finishing` → `done`. The
   16 GB plan lands hash-verified.
3. **Second visit.** Reopening the page with the same drive reaches
   `current` with no click beyond Reconnect.
4. **Interrupted.** Closing the page at about 40% and reopening reaches
   `paused`; Sync finishes the build without downloading verified items
   again.
5. **Update.** With a second catalog in which one item's hash changed, one
   item was added and one removed, the page shows `behind` with those totals
   and Sync applies them: additions verified before removals, no file
   outside the record touched, a planted stray file still present.
6. **Manage.** Switching one collection off and one on returns to `behind`
   with matching totals; Sync applies them. "Reset to recommended" restores
   the default. An over-capacity choice shows "Make it fit".
7. **Adoption.** A drive built by the command-line builder reaches `behind`
   and Sync keeps every file whose hash matches without downloading it.
8. `needs-size`, `too-small`, `unsupported`, `waiting`, `done-gaps` and one
   `problem` case are each reachable in a test.
9. **Reader.** From `file://` in Chromium at 390 × 844 and 1280 × 800: the
   four tabs work; an urgent chip opens its document; a category lists
   books with chapters folded; search for "burns" returns a first-aid
   passage in the first three results; a star survives a reload; Back
   returns from a category to Home.
10. **Static reader.** With scripts disabled the page shows the content of
    5.3 and no app chrome.
11. **Parity.** The Python builder and the browser builder produce the same
    reader files for the same inventory.
12. Screenshots of every state in both themes match the reference files in
    layout and wording.

13. **Space for the library.** On a drive with 959 GB available the slider
    offers 1, 8, 16, 32, 64, 96 … 928 GB and "All 959 GB"; on one with
    59.6 GB it offers 1, 8, 16, 32 GB and "All 59.6 GB". Each stop yields a
    library no larger than the stop. Dragging updates the bar, totals and
    category sizes at every stop without a network or drive request. The
    limit survives Done, Sync and reopening the page, and a lowered limit
    syncs as removals only.

By the owner, on real hardware: picking the top of a USB drive in the folder
dialog; a full sync onto it; opening the drive on an Android phone and an
iPhone, with and without Kiwix.

## 9. Not in this design

Detecting a drive when it is plugged in, without a click. Ejecting the drive
from the page. Syncing from Safari, Firefox or a phone. Saved items that
travel with the drive. Each is outside what a web page or a `file://` page
can do today.
