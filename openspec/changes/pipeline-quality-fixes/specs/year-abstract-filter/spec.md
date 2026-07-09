## ADDED Requirements

### Requirement: Filter papers by minimum year

The pipeline SHALL filter out papers with `published_date` earlier than the configured minimum year (default 2026) before sending them to LLM relevance filtering.

#### Scenario: Paper from 2024 is filtered out

- **WHEN** a paper has `published_date = "2024"` and `min_year = 2026`
- **THEN** the pipeline SHALL exclude this paper from further processing

#### Scenario: Paper from 2026 with valid abstract passes through

- **WHEN** a paper has `published_date = "2026-06-01"` and a non-empty `abstract`
- **THEN** the pipeline SHALL include this paper in the next stage (LLM filtering)

#### Scenario: Paper with no published_date passes year filter

- **WHEN** a paper has `published_date = None` or `published_date = ""`
- **THEN** the pipeline SHALL NOT apply year filtering (passes through)

#### Scenario: Paper from 2025 passes when min_year is configured to 2025

- **WHEN** config `topic.min_year = 2025` and paper has `published_date = "2025"`
- **THEN** the pipeline SHALL include this paper

### Requirement: Filter out papers with empty abstracts

The pipeline SHALL reject papers with empty or whitespace-only `abstract` field before LLM filtering, EXCEPT for papers from the `classic` source (which are manually curated).

#### Scenario: DBLP paper with empty abstract is rejected

- **WHEN** a paper has `source = "dblp"` and `abstract = ""`
- **THEN** the pipeline SHALL exclude this paper

#### Scenario: arXiv paper with abstract passes through

- **WHEN** a paper has `source = "arxiv"` and `abstract = "This paper proposes..."` (non-empty)
- **THEN** the pipeline SHALL include this paper

#### Scenario: Classic paper with empty abstract passes through

- **WHEN** a paper has `source = "classic"` and `abstract = ""`
- **THEN** the pipeline SHALL include this paper (classic source is manually curated, exempt from empty-abstract check)

### Requirement: Log filtering statistics

The pipeline SHALL log how many papers were rejected due to year and empty-abstract checks respectively.

#### Scenario: Filter logs after validation

- **WHEN** papers are filtered in the validation stage
- **THEN** the log SHALL show counts of rejected-by-year and rejected-by-abstract, plus the total passing count
