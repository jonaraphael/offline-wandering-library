# OWL scripts

Run the documented commands from the repository root after installing OWL.
See the [operating guide](../docs/usage.md), [validation guide](../docs/validation.md)
and [acquisition guide](../docs/content-acquisition.md) for full examples.
One-off acquisition, inspection and trial tools are in [acquisition/](acquisition/).
The [acquisition archive](../docs/archive/README.md) records when and how they were used.
Catalog receipts that record an original command or code hash use the path
from the commit that produced the receipt.

| Script | What it does | Who runs it |
| --- | --- | --- |
| `acquire_content.py` | Runs the reviewed content acquisition commands. | Catalog maintainers |
| `acquisition_trial_status.py` | Summarizes staged trial progress and receipts. | Acquisition supervisor, tests |
| `audit_manual_dependencies.py` | Audits dependencies in captured manual packages. | Acquisition jobs |
| `build_archive_passages.py` | Extracts passages from reviewed archive ranges for indexing. | Search maintainers |
| `build_atlas.py` | Builds the offline topic atlas on a drive. | Drive builders, CI |
| `build_capacity_ladder.py` | Regenerates or checks the catalog's storage recommendations. | Catalog maintainers, CI |
| `build_content_docs.py` | Regenerates or checks the content inventory and capacity docs. | Catalog maintainers, CI |
| `build_device_test_kit.py` | Creates a small offline library for device checks. | Device testers |
| `build_drive.py` | Plans a library or builds it on the selected drive. | Drive builders, CI |
| `build_impact_routes.cjs` | Generates search impact routes from local index data. | Search maintainers |
| `build_job.py` | Starts, inspects, cancels and resumes background drive builds. | Drive builders |
| `build_kiwix_pins.py` | Rebuilds Kiwix piece pins from publisher metadata. | Catalog maintainers |
| `build_pages.py` | Builds the Pages artifact and generates mirror or relay metadata. | Release maintainers, CI |
| `build_query_index.cjs` | Generates the offline search query index. | Search maintainers, tests |
| `build_search_routes.cjs` | Generates the routing data that selects search shards. | Search maintainers |
| `build_search_shards.py` | Precomputes search shards from local source files. | Search maintainers |
| `build_search_transformer.py` | Packs pinned transformer inputs for the offline reader. | Search maintainers |
| `build_selector.py` | Regenerates or checks standalone `SELECT.html`. | Catalog maintainers, CI |
| `build_story_ladder.py` | Renders the story-ladder PDFs from pinned Gutenberg HTML and checks their catalog entries. | Catalog maintainers |
| `build_wikimed_phone.py` | Builds the WikiMed volumes that phones can open as PDFs. | Catalog maintainers |
| `check_browser_resume.cjs` | Exercises browser transfer resume and disk-full recovery. | Browser testers, CI |
| `check_content_policy.py` | Checks the catalog against content type and admission rules. | Catalog maintainers, CI |
| `check_documents.cjs` | Checks exact captured document editions in a browser. | Content reviewers |
| `check_lessons.py` | Checks captured offline lessons against their reviewed interactions. | Content reviewers |
| `check_links.py` | Checks publisher URLs and samples Pages and relay routes. | Catalog maintainers, scheduled CI |
| `check_manual_package.py` | Checks a pinned manual package in a browser. | Acquisition jobs, tests |
| `check_manuals.cjs` | Runs browser checks for captured manuals. | Content reviewers |
| `check_pages_profiles.py` | Checks that production Pages recommendations cover the essential files. | Release CI |
| `check_phet.cjs` | Exercises offline PhET simulation controls in a browser. | Content reviewers, tests |
| `check_selection_policy.py` | Checks catalog selections against the priority and capacity rules. | Catalog maintainers, CI |
| `check_staged_admission.py` | Validates staged content and its review evidence. | Catalog reviewers, tests |
| `copy_drive.py` | Copies a verified library to a second drive. | Drive builders, CI |
| `discover_hesperian_fallback.py` | Inventories publisher fallback editions for review. | Acquisition reviewers, tests |
| `discover_kolibri.py` | Inventories Kolibri channels and publisher metadata. | Acquisition reviewers, tests |
| `discovery.py` | Builds or assembles the offline discovery index and atlas. | Drive builders, search maintainers |
| `export_direct.py` | Exports direct-reading editions from pinned inputs. | Catalog maintainers, tests |
| `freeze_map_selection.py` | Freezes the reviewed map selection manifest. | Catalog maintainers |
| `import_sections.py` | Imports text sections into atlas source data. | Atlas maintainers, tests |
| `inspect_kolibri_capture.py` | Checks a captured Kolibri package's structure and pins. | Acquisition jobs, tests |
| `inspect_kolibri_census.py` | Summarizes the inspected Kolibri archive inventory. | Acquisition jobs, tests |
| `inspect_map_capture.py` | Checks captured map packages and records review evidence. | Acquisition jobs |
| `inspect_midwives_digital.py` | Inspects captured digital Midwives source evidence. | Acquisition jobs |
| `inspect_midwives_response.py` | Checks captured publisher responses for review. | Acquisition jobs |
| `inspect_ocw_packages.py` | Inspects captured OpenCourseWare packages. | Acquisition jobs |
| `inspect_survivor_capture.py` | Checks captured Survivor Library files for review. | Acquisition jobs, tests |
| `inspect_zim_candidates.py` | Inventories captured ZIM candidates. | Acquisition jobs, tests |
| `manual_link_checks.cjs` | Provides link-check helpers for manual browser checks. | Manual checkers, tests |
| `prepare_catalog_capture.py` | Converts catalog sources into a reviewed capture plan. | Acquisition reviewers, tests |
| `prepare_existing_evidence.py` | Prepares review evidence from an existing capture. | Catalog maintainers |
| `prepare_ocw_complete_preview.py` | Prepares a full captured OpenCourseWare preview. | Acquisition jobs, tests |
| `prepare_ocw_followup.py` | Prepares a follow-up OpenCourseWare capture and review. | Acquisition jobs, tests |
| `prepare_ocw_preview.py` | Creates a bounded preview of a captured course package. | Acquisition jobs |
| `prepare_openssh.py` | Prepares the reviewed OpenSSH acquisition package. | Catalog maintainers |
| `prepare_review_packets.py` | Packages capture evidence for review. | Acquisition jobs, tests |
| `prepare_sqlite_package.py` | Prepares a pinned SQLite documentation package. | Acquisition jobs, tests |
| `prepare_stackoverflow.py` | Prepares pinned Stack Overflow acquisition inputs. | Acquisition jobs, tests |
| `prepare_survivor_batch.py` | Prepares a Survivor Library review batch. | Acquisition reviewers, tests |
| `probe_capacity.mjs` | Measures or checks capacity probe behavior on test media. | Device testers, manual CI |
| `probe_source_batches.py` | Checks source viability for reviewed batches. | Catalog maintainers, acquisition jobs |
| `probe_source_pins.py` | Probes publisher sources against their expected pins. | Catalog maintainers |
| `relocate_map_review.py` | Updates review evidence after a staged map package moves. | Acquisition reviewers, tests |
| `review_manual_references.py` | Reviews manual archive references against staged files. | Acquisition reviewers, tests |
| `review_ocw_course.py` | Runs the review checks for a captured OpenCourseWare course. | Acquisition jobs, tests |
| `search_benchmark.py` | Evaluates offline search on fixed queries and reader fixtures. | Search maintainers, CI |
| `search_timing.cjs` | Measures offline reader search timings. | Search maintainers, tests |
| `summarize_phet.py` | Summarizes PhET browser evidence against its pinned inputs. | Content reviewers, tests |
| `trial_direct_previews.py` | Runs bounded previews for direct-reading editions. | Acquisition jobs, tests |
| `trial_supervisor.py` | Runs and monitors staged acquisition trials. | Acquisition maintainers, tests |
| `validate_acquisition.py` | Validates acquisition records and staged review inputs. | Catalog maintainers, tests |
| `validate_capacity_spec.py` | Checks the reviewed capacity and source-pin specification. | Catalog maintainers |
| `validate_catalog.py` | Validates catalog metadata, source pins and paths. | Catalog maintainers, CI |
| `verify.py` | Verifies integrity and completeness of a built library. | Drive builders, CI |
