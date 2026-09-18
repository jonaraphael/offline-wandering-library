# Original atlas demonstration

These small CC0 fixtures demonstrate the topic mechanism; they are not emergency
guidance or production collection coverage. They use only original files from
`assets/demo/`, selected by `catalog/demo.yaml`.

Build and inspect the demo without network downloads:

```bash
python scripts/build_drive.py /tmp/owl-atlas-demo \
    --catalog catalog/demo.yaml --profile demo --allow-local \
    --navigation-dir catalog/demo-navigation
python scripts/verify.py /tmp/owl-atlas-demo --strict
```

Alternatively, add or regenerate only its human navigation after an ordinary
demo build:

```bash
python scripts/build_atlas.py /tmp/owl-atlas-demo \
    --catalog catalog/demo.yaml --allow-local \
    --navigation-dir catalog/demo-navigation --strict-coverage
```

Open `START_HERE.html` and `INDEX/topics.html`. The demonstration includes:

- One build-process topic shared by subject and learning parents.
- Reciprocal related links between the two subject entrances.
- An ambiguous “Systems” A–Z label that offers both relevant topics.
- A reviewed local HTML anchor at the original textbook's inline SVG diagram.
- Source version, license, attribution, section location, and complete-document
  fallback alongside the diagram link.

`sections/demo_textbook.yaml` pins the exact original HTML bytes. The diagram
claim is specific to the reviewed `diagram-title` location. Editing the fixture
requires updating its catalog pin and reviewing the section map; a stale map
must fail publication.

The [atlas guide](../../docs/topic-atlas.md) describes the production/editorial
workflow and remaining device limitations. Local HTML links can still be blocked
by a phone's file preview even though the pages require no JavaScript.
