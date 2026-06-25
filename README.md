# Career Viability Dashboard

A labor market analytics project that answers the question: **if you're choosing a college major today, which career paths offer the strongest combination of earning potential, employment growth, and projected demand?**

The deliverable is a Power BI dashboard published to Power BI Service, backed by a Python data pipeline that pulls and processes BLS labor market data. Together they demonstrate Python for API data engineering, Power Query for data modeling, DAX for calculated measures, and Power BI for dashboard design.

---

## What This Project Produces

**Python pipeline** (`pipeline.py`) — pulls OEWS wage data and Employment Projections from BLS, joins them at the SOC occupation code level, computes Career Viability Index scores, and exports a clean CSV ready to load into Power BI.

**Power BI dashboard** — four views:
- Ranked leaderboard of occupations by Career Viability Index score
- Side-by-side comparison of two selected occupations
- Major-to-career mapping (college major → career path → CVI score)
- Trend view: wage and employment trajectory over available years

---

## Career Viability Index

The CVI is a composite score (0–100) per occupation that weights three BLS signals:

| Signal | Weight | Source | Why |
|--------|--------|--------|-----|
| Median annual wage (percentile rank) | 40% | OEWS May 2023 | Realized market outcome; highest data reliability |
| 10-year projected employment growth % (percentile rank) | 35% | EP 2023-2033 | Forward-looking career risk |
| Projected annual openings (percentile rank) | 25% | EP 2023-2033 | Volume of entry opportunities per year |

Scores are percentile ranks normalized to 0–100, then weighted. An occupation scoring 80 is in the top 20% of all occupations on that combined basis. Weighting rationale: [ADR-003](docs/decisions/003-cvi-weighting.md).

---

## Data Sources

| Dataset | Source | Access Method | Coverage |
|---------|--------|---------------|----------|
| OEWS May 2023 (wages, employment) | BLS | ZIP flat file | ~800 detailed occupations, national |
| EP Table 1.2 (2023-2033 projections) | BLS | XLSX flat file | ~800 detailed occupations |
| EP illustrative series | BLS API v2 | Timeseries API | 5 occupations (API demonstration) |
| CIP-SOC crosswalk | NCES | Reference CSV | Major-to-career mapping |

**Why flat files for OEWS?** The OEWS flat file contains all occupations in a single consistent vintage. Pulling 800 individual OEWS series via the API would cost 16+ API requests, risk vintage inconsistency, and still miss fields (employment count, wage percentiles) that are not available as standalone series. See [ADR-001](docs/decisions/001-oews-flat-files-vs-api.md).

**Why EP annual openings instead of JOLTS for demand?** JOLTS does not publish at the SOC occupation grain — it reports by industry sector only, requiring a multi-step crosswalk that introduces modeled error. EP annual openings are a direct BLS projection at the SOC grain. See [ADR-002](docs/decisions/002-demand-signal-annual-openings-vs-jolts.md).

---

## Data Limitations

These limitations are disclosed in the dashboard and documented here for portfolio transparency.

**Recency.** OEWS wage data reflects May 2023. EP projections cover 2023-2033, published 2024. These are the most current available releases; they are not perfectly synchronized.

**Wage suppression.** BLS suppresses wages for occupations with very few workers or where disclosure would identify individual employers. These occupations appear in the output with `wage_suppressed = True` and are excluded from CVI ranking. They remain visible in the dashboard with a flag.

**SOC version mismatches.** OEWS and EP target 2018 SOC codes, but some occupations are aggregated differently between programs. Occupations present in one dataset but absent from the other are flagged as `soc_mismatch_flag = True` in the output and logged during the pipeline run.

**Projection uncertainty.** BLS 10-year projections carry inherent uncertainty, particularly for technology-adjacent occupations. The CVI should be interpreted as a **relative ranking tool**, not a forecast. An occupation ranked 85th today may not still rank 85th in 2033.

**Demand signal correlation.** Annual openings correlate with occupation size. Large occupations generate more replacement demand regardless of growth. The 25% weight limits but does not eliminate this bias.

**Major-to-career mapping.** The CIP-SOC crosswalk reflects typical educational pathways, not guarantees. See [ADR-004](docs/decisions/004-major-career-crosswalk.md).

---

## Setup

**Prerequisites:** Python 3.11+

```bash
# Clone the repo
git clone https://github.com/lkomenski/career-viability-dashboard.git
cd career-viability-dashboard

# Install dependencies
pip install -r requirements.txt

# Set up your BLS API key
cp .env.example .env
# Edit .env and add your key from https://data.bls.gov/registrationEngine/
```

**Run the pipeline:**

```bash
python pipeline.py
```

Output is written to `output/career_viability_data.csv` and `output/pipeline.log`. The `output/` directory is gitignored — the CSV is a generated artifact, not source data.

---

## Output Schema

One row per detailed SOC occupation (~800 rows). Designed for direct import into Power BI with no further transformation in Power Query.

| Column | Type | Description |
|--------|------|-------------|
| `soc_code` | string | 7-character SOC code (e.g., `15-1252`) |
| `occupation_title` | string | BLS occupation name |
| `soc_major_group_code` | string | 2-digit SOC major group (e.g., `15`) |
| `soc_major_group` | string | Major group name (e.g., `Computer and Mathematical`) |
| `median_annual_wage` | integer | OEWS median annual wage (May 2023) |
| `wage_25th_pct` | integer | 25th percentile annual wage |
| `wage_75th_pct` | integer | 75th percentile annual wage |
| `employment_count` | integer | OEWS total employment |
| `employment_2023` | integer | EP baseline employment (2023) |
| `employment_2033` | integer | EP projected employment (2033) |
| `employment_change_number` | integer | Net employment change 2023-2033 |
| `employment_change_pct` | float | Percent employment change 2023-2033 |
| `annual_openings` | integer | Projected avg. annual openings 2023-2033 |
| `typical_entry_education` | string | BLS typical entry-level education |
| `api_ep_change_pct_check` | float | API-sourced growth % (5 occupations only) |
| `wage_pct_rank` | float | Wage percentile rank 0–100 |
| `growth_pct_rank` | float | Growth rate percentile rank 0–100 |
| `demand_pct_rank` | float | Annual openings percentile rank 0–100 |
| `cvi_score` | float | Career Viability Index (0–100) |
| `cvi_complete` | boolean | True if all three rank inputs are non-null |
| `wage_suppressed` | boolean | True if BLS suppressed the wage |
| `soc_mismatch_flag` | boolean | True if SOC code not found in EP file |
| `data_flag` | string | Human-readable quality flag(s) |
| `survey_year` | integer | OEWS survey year (2023) |
| `projection_period` | string | EP projection period (`2023-2033`) |

---

## Architecture Decisions

Significant decisions made during design are documented as ADRs (Architecture Decision Records) in [`docs/decisions/`](docs/decisions/). Each ADR explains the context, the decision, the rationale, alternatives considered, and consequences.

| ADR | Decision |
|-----|----------|
| [ADR-001](docs/decisions/001-oews-flat-files-vs-api.md) | Use OEWS flat files instead of BLS timeseries API for wage data |
| [ADR-002](docs/decisions/002-demand-signal-annual-openings-vs-jolts.md) | Use EP annual openings as the demand signal instead of JOLTS |
| [ADR-003](docs/decisions/003-cvi-weighting.md) | CVI weighting: Wage 40%, Growth 35%, Demand 25% |
| [ADR-004](docs/decisions/004-major-career-crosswalk.md) | Major-to-career mapping requires a supplemental CIP-SOC crosswalk |

---

## Power BI Data Model

The Power BI model is a star schema. The fact table is `Occupations` (the pipeline output CSV). Dimension tables are smaller lookup tables that support filtering.

```
Majors (cip_code PK)
    └── CIP_SOC_Bridge (cip_code, soc_code)  [many-to-many bridge]
            └── Occupations (soc_code PK)    [fact table — pipeline output]
                    └── OccupationGroups (soc_major_group_code PK)
```

DAX measures (to be documented as the dashboard is built):
- `CVI Score` — surfaces the pre-calculated `cvi_score` column
- `CVI Dynamic` — user-adjustable weighted composite (second pass, requires parameter tables)
- `Wage vs. National Median` — dollar delta from overall median wage
- `Growth Tier` — categorical label (High / Moderate / Low) based on `growth_pct_rank`

---

## Project Status

- [x] Architecture design and decision documentation
- [x] Python pipeline (ingestion, transformation, CVI scoring, export)
- [ ] Power BI data model
- [ ] Dashboard — Leaderboard view
- [ ] Dashboard — Comparison view
- [ ] Dashboard — Major-to-career view
- [ ] Dashboard — Trend view
- [ ] Publish to Power BI Service
