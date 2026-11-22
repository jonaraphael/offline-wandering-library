# Choose a library with the offline selector

Open [SELECT.html](../SELECT.html) in a browser with JavaScript enabled. The page
contains its own catalog and planner. You can make a selection without internet
access and copy commands for the Python builder. For a browser that writes
straight to the drive, use the [Pages builder](pages-builder.md). Its connected
Manage screen has a storage slider that saves a limit with the drive's choice.

## Choose a library

Choose the drive's size from 16 GB, 32 GB, 64 GB, 128 GB, 256 GB, 512 GB or 1 TB.
The page opens with the 64 GB recommendation. The storage bar and totals update
as you change the selection. The summary and the category rows show how much
space your files will use. The planner also reserves space for search and the
reader. [Common-size recommendations](content-selection.md) list the default
collections by capacity.

- Expand a category to see its collections. Use **Find a collection** to match
  collection names, descriptions and file titles.
- Use a collection switch to include or exclude it. Collections marked
  **Essential** can also be switched off. When a collection offers editions,
  choose one to change which files it includes. **Choose files** lets you edit
  an edition's file list.
- Use **Reset to recommended** to restore the selection for the current size.
  When the selection exceeds the available space, **Make it fit** drops the
  least essential selections until the library fits.
- Open **Advanced** for the FAT32 option, bulk include and exclude for matching
  files, and storage accounting. Bulk changes apply to the matching files in
  the current editions. The accounting table lists the selection, the reserve
  and any issues to resolve before building.

## Build it with the desktop tool

1. Enter the path to the library folder on your drive and choose your terminal
   type. Leave **Build with the files available now** off unless you want to
   accept incomplete collections. Every included file is still verified.
2. Select **Copy plan command** and run it from the installed OWL repository.
   This checks the selection and the drive's free space before any download or
   write.
3. Select **Copy build command** and run it from the same repository. The command
   uses `--detach`, which starts a background job and prints the job directory.
   See [unattended builds](unattended-builds.md) for status, cancellation and
   resume. The builder downloads to the library folder and writes
   `START_HERE.html` for offline reading and search.

The command carries the chosen capacity as `--capacity-bytes`. Edition changes
use `--edition RESOURCE=EDITION`. A custom subset uses the repeatable
`--resource-assets RESOURCE=ASSET,ASSET` flag. A file or collection excluded here
is left out of the generated build command. To make an existing drive match a
new selection, use Sync in the Pages builder.

## Regenerate the page

After updating the catalog, planner or selector template, regenerate the page
from the installed Python project.

```bash
python scripts/build_selector.py
python scripts/build_selector.py --check
```

Keep the generated file with its matching repository revision and run the plan
command before starting a build.
