# Career Viability Dashboard

> Which career paths offer the strongest combination of earning potential, employment growth, and projected demand — and how does that picture differ by field of study?

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-2.1+-150458?style=flat-square&logo=pandas&logoColor=white)
![Power BI](https://img.shields.io/badge/Power%20BI-Dashboard-F2C811?style=flat-square&logo=powerbi&logoColor=black)
![BLS](https://img.shields.io/badge/Data-BLS%20Public%20API-003366?style=flat-square)
![Status](https://img.shields.io/badge/Status-Pipeline%20Complete-brightgreen?style=flat-square)

A labor market analytics project built for a data analytics portfolio. The Python pipeline ingests raw BLS labor market data, computes a composite Career Viability Index (CVI) score per occupation, and exports a clean flat file for Power BI. The dashboard answers the analytical question above across four views: ranked leaderboard, side-by-side comparison, major-to-career mapping, and wage/employment trend.

**Skills demonstrated:** Python · BLS Public Data API · pandas · Power Query · DAX · Power BI Service

---

## Table of Contents

- [Analytical Question](#analytical-question)
- [Career Viability Index](#career-viability-index)
- [Pipeline Architecture](#pipeline-architecture)
- [Data Sources](#data-sources)
- [Data Limitations](#data-limitations)
- [Setup and Usage](#setup-and-usage)
- [Pipeline Output](#pipeline-output)
- [Output Schema](#output-schema)
- [Architecture Decisions](#architecture-decisions)
- [Power BI Data Model](#power-bi-data-model)
- [Project Status](#project-status)

---

## Analytical Question

**"If you are choosing a college major today, which career paths offer the strongest combination of earning potential, employment growth, and projected demand — and how does that picture differ by field of study?"**

This is an inherently analytical question, not a reporting question. The answer is not a single number — it is a ranked, composite view of the labor market that changes depending on how you weight the three signals. The dashboard is designed to make that weighting transparent and adjustable.

---

## Career Viability Index

The CVI is a composite score (0–100) per occupation. Each input is percentile-ranked across all ~830 occupations in the dataset before weighting, so the score is always a relative measure — it tells you where an occupation stands compared to the full field, not what its absolute values are.

| Signal | Weight | Source | Rationale |
|--------|--------|--------|-----------|
| Median annual wage | **40%** | OEWS May 2023 | Realized market outcome; highest data reliability |
| 10-year projected employment growth % | **35%** | EP 2024–2034 | Forward-looking career risk indicator |
| Projected annual openings | **25%** | EP 2024–2034 | Volume of entry opportunities; flow measure, not stock |

An occupation scoring 80 ranks in the top 20% of all occupations on a weighted basis. Occupations with suppressed wages or missing projection data receive a null CVI and are surfaced in the dashboard with a data quality flag rather than omitted.

Full weighting rationale: [ADR-003](docs/decisions/003-cvi-weighting.md)

---

## Pipeline Architecture

```
┌─────────────────────┐   ┌──────────────────────┐   ┌──────────────────────────┐
│   BLS OEWS ZIP      │   │   BLS EP XLSX        │   │   BLS Timeseries API     │
│   national flat     │   │   Occupation.xlsx    │   │   5 series (illustrative)│
│   file, May 2023    │   │   Table 1.2          │   │   EP growth % by SOC     │
└────────┬────────────┘   └────────┬─────────────┘   └─────────────┬────────────┘
         │                         │                               │
         v                         v                               v
  download_oews()           download_ep()              pull_illustrative_api()
  831 occupations           1090 rows parsed           graceful fallback on miss
  20 suppressed wages       sheet auto-detected
         │                         │                               │
         └────────────┬────────────┘                               │
                      │                                            │
                      v                                            │
         join_and_flag_mismatches()                                │
         Left join on soc_code                                     │
         831 rows · 831 matched · 0 unmatched                      │
                      │                                            │
                      └──────────────────┬─────────────────────────┘
                                         │
                                         v
                            add_percentile_ranks()
                            wage / growth / demand → 0–100 scale
                                         │
                                         v
                               add_cvi_score()
                               811 complete · 20 null (suppressed wages)
                                         │
                                         v
                      ┌──────────────────┴──────────────────┐
                      │    career_viability_data.csv        │
                      │    831 rows · 24 columns            │
                      │    ready for Power BI import        │
                      └─────────────────────────────────────┘
```

### Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| OEWS access method | Flat file (ZIP) | Single consistent vintage; flat file has percentile columns unavailable as API series |
| Demand signal | EP annual openings | SOC-grain flow measure; JOLTS is industry-grain only |
| CVI missing values | Null, not imputed | Partial scores would rank against peers with complete data |
| SOC mismatches | Flagged, not dropped | Preserves all OEWS occupations; Power BI can filter |

---

## Data Sources

| Dataset | Program | Vintage | Access | Coverage |
|---------|---------|---------|--------|----------|
| Occupational wages | BLS OEWS | May 2023 | ZIP flat file | 831 detailed occupations, national |
| Employment projections | BLS EP Table 1.2 | 2024–2034 | XLSX flat file (local) | 831 matched occupations |
| EP illustrative series | BLS Timeseries API v2 | 2024 | REST API | 5 occupations (API skill demonstration) |
| Major-to-career mapping | NCES CIP-SOC crosswalk | — | Reference CSV | In development |

**Data vintage gap:** OEWS wage data is from May 2023. EP projections cover 2024–2034 (published 2025). These are the two most current available BLS releases at time of analysis; they are not from the same reference period. This is disclosed in the dashboard. See [Data Limitations](#data-limitations).

---

## Data Limitations

All limitations below are disclosed in the dashboard. Documentation here is for portfolio transparency and to demonstrate analytical honesty.

**Data vintage gap.** OEWS wages reflect May 2023 employer surveys. EP projections cover 2024–2034. The one-year gap is a structural limitation of BLS publication cadences — the two programs publish on different schedules and cannot always be perfectly aligned. Both datasets represent the most current published releases at time of analysis.

**Wage suppression.** BLS suppresses wages (`#` or `*` in the source file) for occupations with very low employment or where disclosure could identify individual employers. 20 of 831 occupations are suppressed. These appear in the output with `wage_suppressed = True`, receive a null CVI, and are visible in the dashboard with a quality flag.

**SOC aggregation differences.** EP Table 1.2 publishes both detailed occupations and minor/broad group subtotals (e.g., `15-1200 Software and Web Developers`). OEWS publishes only detailed occupations. The 259 EP codes with no OEWS match are these aggregate rows — not a data quality problem, an expected structural difference between the two programs.

**Projection uncertainty.** BLS 10-year projections carry inherent forecast uncertainty, particularly for technology-adjacent occupations where structural change is rapid. The CVI is designed as a **relative ranking tool at a point in time**, not a forecast. Rankings may shift materially as new EP vintages are published.

**Demand signal correlation with size.** Annual openings correlate with occupation size because large occupations generate more replacement demand (retirements, career changes) regardless of net growth. The 25% weight on demand limits but does not eliminate this size bias. See [ADR-002](docs/decisions/002-demand-signal-annual-openings-vs-jolts.md).

**Major-to-career mapping coverage.** The NCES CIP-SOC crosswalk reflects typical educational pathways, not the full distribution of outcomes. General-purpose majors (Liberal Arts, General Studies) have weak SOC mappings. The dashboard frames this view as "common paths from this major," not "careers this major leads to." See [ADR-004](docs/decisions/004-major-career-crosswalk.md).

---

## Setup and Usage

**Prerequisites:** Python 3.11+, a free BLS API key

```bash
# Clone
git clone https://github.com/lkomenski/career-viability-dashboard.git
cd career-viability-dashboard

# Install dependencies
pip install -r requirements.txt

# Configure BLS API key
cp .env.example .env
# Add your key: https://data.bls.gov/registrationEngine/
```

**EP flat file (one-time manual download)**

The BLS EP file requires a manual download due to server-side access controls on direct requests. Download `Occupation.xlsx` from:

> https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm

Save it to `data/Occupation.xlsx`. The pipeline reads from this path by default (`EP_TABLE_LOCAL` in `pipeline.py`).

**Run**

```bash
python pipeline.py
```

Output is written to `output/career_viability_data.csv` and `output/pipeline.log`. The `output/` directory is gitignored — the CSV is a generated artifact.

---

## Pipeline Output

Validated run — 25 June 2026:

| Metric | Value |
|--------|-------|
| OEWS occupations loaded | 831 |
| Suppressed wages | 20 |
| EP occupations matched | 831 (100%) |
| EP aggregate rows (unmatched, expected) | 259 |
| Complete CVI scores | 811 |
| Null CVI (suppressed wage, no rank) | 20 |
| Output columns | 24 |
| Runtime | ~3 seconds |

---

## Output Schema

One row per detailed SOC occupation (831 rows). Column order is designed for direct import into Power BI with no transformation needed in Power Query.

<details>
<summary>Expand full schema (24 columns)</summary>

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `soc_code` | string | OEWS | 7-character SOC code (e.g., `15-1252`) — primary key |
| `occupation_title` | string | OEWS | BLS occupation name |
| `soc_major_group_code` | string | derived | 2-digit SOC prefix (e.g., `15`) |
| `soc_major_group` | string | derived | Major group label (e.g., `Computer and Mathematical`) |
| `median_annual_wage` | integer | OEWS | Median annual wage, May 2023 |
| `wage_25th_pct` | integer | OEWS | 25th percentile annual wage |
| `wage_75th_pct` | integer | OEWS | 75th percentile annual wage |
| `employment_count` | integer | OEWS | Total employment, May 2023 |
| `employment_2024` | integer | EP | Baseline employment (2024) |
| `employment_2034` | integer | EP | Projected employment (2034) |
| `employment_change_number` | integer | EP | Net employment change, 2024–2034 |
| `employment_change_pct` | float | EP | Percent employment change, 2024–2034 |
| `annual_openings` | integer | EP | Projected avg. annual openings, 2024–2034 |
| `typical_entry_education` | string | EP | BLS typical entry-level education |
| `api_ep_change_pct_check` | float | BLS API | API-sourced growth % (5 occupations only; cross-validation) |
| `wage_pct_rank` | float | calculated | Wage percentile rank, 0–100 |
| `growth_pct_rank` | float | calculated | Growth rate percentile rank, 0–100 |
| `demand_pct_rank` | float | calculated | Annual openings percentile rank, 0–100 |
| `cvi_score` | float | calculated | Career Viability Index (0–100); null if any input is missing |
| `cvi_complete` | boolean | calculated | True if all three rank inputs are non-null |
| `wage_suppressed` | boolean | OEWS | True if BLS suppressed the wage for this occupation |
| `soc_mismatch_flag` | boolean | derived | True if SOC code absent from EP file |
| `data_flag` | string | derived | Pipe-delimited quality flags for Power BI tooltips |
| `survey_year` | integer | OEWS | OEWS survey reference year (2023) |
| `projection_period` | string | EP | EP projection window (`2024-2034`) |

</details>

---

## Architecture Decisions

Design decisions are documented as Architecture Decision Records (ADRs) in [`docs/decisions/`](docs/decisions/). Each ADR covers context, the decision made, rationale, alternatives considered, and consequences. ADR format follows the Nygard convention.

| # | Decision | Status |
|---|----------|--------|
| [ADR-001](docs/decisions/001-oews-flat-files-vs-api.md) | Use OEWS flat files instead of BLS timeseries API for wage data | Accepted |
| [ADR-002](docs/decisions/002-demand-signal-annual-openings-vs-jolts.md) | Use EP annual openings as the demand signal instead of JOLTS | Accepted |
| [ADR-003](docs/decisions/003-cvi-weighting.md) | CVI weighting: Wage 40%, Growth 35%, Demand 25% | Accepted |
| [ADR-004](docs/decisions/004-major-career-crosswalk.md) | Major-to-career mapping requires a supplemental NCES CIP-SOC crosswalk | Accepted |

---

## Power BI Data Model

The model follows a star schema pattern. `Occupations` (the pipeline output CSV) is the fact table. Dimension tables support filtering and the major-to-career view.

```
Majors (cip_code PK)
    └── CIP_SOC_Bridge (cip_code, soc_code)    ← many-to-many bridge table
              └── Occupations (soc_code PK)     ← fact table (pipeline output)
                        └── OccupationGroups (soc_major_group_code PK)
```

**Planned DAX measures**

| Measure | Purpose |
|---------|---------|
| `CVI Score` | Surfaces the pre-calculated `cvi_score` column |
| `CVI Dynamic` | User-adjustable weighted composite via parameter slicers (second pass) |
| `Wage vs. National Median` | Dollar delta from the median wage across all occupations |
| `Growth Tier` | Categorical label (High / Moderate / Declining) from `growth_pct_rank` |
| `Demand Tier` | Categorical label (High / Moderate / Low) from `demand_pct_rank` |

The `CVI Dynamic` measure normalizes user-selected weights to sum to 1.0 using `DIVIDE()`, so the score remains on a 0–100 scale even when sliders do not sum to 100:

```dax
CVI Dynamic =
VAR WW = SELECTEDVALUE(WageWeightParam[Value], 40) / 100
VAR GW = SELECTEDVALUE(GrowthWeightParam[Value], 35) / 100
VAR DW = SELECTEDVALUE(DemandWeightParam[Value], 25) / 100
VAR Total = WW + GW + DW
RETURN
    DIVIDE(
        WW * SELECTEDVALUE(Occupations[wage_pct_rank])
            + GW * SELECTEDVALUE(Occupations[growth_pct_rank])
            + DW * SELECTEDVALUE(Occupations[demand_pct_rank]),
        Total
    )
```

---

## Project Status

| Phase | Status |
|-------|--------|
| Architecture design and ADR documentation | Complete |
| Python pipeline — ingestion, join, CVI scoring, export | Complete |
| Pipeline validation (831 occupations, 811 CVI scores) | Complete |
| Power BI — data model and relationships | Not started |
| Power BI — Leaderboard view | Not started |
| Power BI — Comparison view | Not started |
| Power BI — Major-to-career view | Not started |
| Power BI — Trend view | Not started |
| Publish to Power BI Service | Not started |
