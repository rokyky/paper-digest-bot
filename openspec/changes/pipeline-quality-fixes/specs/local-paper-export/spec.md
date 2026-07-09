## ADDED Requirements

### Requirement: Save pushed digest as local markdown after successful push

After each successful Feishu push, the pipeline SHALL write the digest content (paper metadata + all sections) to a local markdown file.

#### Scenario: Successful push triggers local save

- **WHEN** the pipeline successfully pushes a digest to Feishu (pusher returns success > 0)
- **THEN** the pipeline SHALL create a markdown file at the configured local directory
- **AND** the file SHALL contain the paper title, authors, source, URL, and all non-empty digest sections

#### Scenario: Local file path structure

- **WHEN** a paper has `published_date = "2026-06-01"` and `external_id = "arXiv:2606.12345"`
- **THEN** the output path SHALL be `<local-dir>/2026/06/arXiv_2606.12345.md`

#### Scenario: Duplicate push does not overwrite

- **WHEN** the local markdown file already exists for this paper (same external_id)
- **THEN** the pipeline SHALL skip writing (return without error)

### Requirement: Configurable local output directory

The local output directory SHALL be configurable and default to `storage/pushed/` within the project root.

#### Scenario: Configure custom output directory

- **WHEN** `config.push.local_export_dir` is set to `"E:/my-projects/arxiv-paper/raw"`
- **THEN** the pipeline SHALL save markdown files under that path
