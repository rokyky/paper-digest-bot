## ADDED Requirements

### Requirement: Export historical pushed papers to local markdown files

The system SHALL provide a standalone script `scripts/export_pushed_papers.py` that reads from `digest_queue.json` (pushed entries) and `pushed_ids.json` to export all historically pushed papers as local markdown files.

#### Scenario: Export from queue with digest content

- **WHEN** `digest_queue.json` contains entries with `pushed = true` and full digest data
- **AND** the script is run without arguments
- **THEN** the script SHALL create markdown files for each pushed entry
- **AND** the script SHALL create an `INDEX.md` in the output directory listing all exported papers

#### Scenario: Export with no pushed entries

- **WHEN** `digest_queue.json` is empty or all entries are unpushed
- **THEN** the script SHALL report zero papers exported and display a warning

#### Scenario: Export with custom output directory

- **WHEN** the script is run with `--outdir "E:/my-projects/arxiv-paper/raw"`
- **THEN** the script SHALL use that directory as the output root instead of the default
