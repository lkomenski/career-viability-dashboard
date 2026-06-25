# ADR-001: Use OEWS Flat Files Instead of BLS Timeseries API for Wage Data

**Status:** Accepted  
**Date:** 2025-06  
**Decider:** Leena Komenski

---

## Context

The analytical question requires median annual wage data for approximately 800 detailed occupations from the BLS Occupational Employment and Wage Statistics (OEWS) program. There are two ways to obtain this data from BLS:

1. **BLS Timeseries API v2** — request individual series IDs per occupation and parse JSON responses
2. **OEWS national flat file** — download a single ZIP file containing all occupations for a given survey year

The project brief required a BLS API key and referenced the timeseries API (`https://api.bls.gov/publicAPI/v2/timeseries/data/`) as the intended data source.

---

## Decision

Use the **OEWS national flat file** (ZIP → XLSX) for all wage data. Use the **BLS Timeseries API** for an illustrative pull on the Employment Projections side only.

---

## Rationale

### Why the flat file is the right engineering choice for OEWS

**Query budget.** The BLS API allows 50 series per request with a registered key. Pulling median annual wages for ~800 occupations requires a minimum of 16 API requests. Each OEWS series ID encodes one occupation × one data type × one geography, so pulling wage + employment count + two percentile columns for national scope requires roughly 64 requests. A registered key allows 500 requests per day — so this is feasible, but it burns a significant share of the daily budget for data that could be obtained with a single download.

**Consistency guarantee.** When you request individual OEWS series via the API, you are pulling from the timeseries database, which stores historical observations. The OEWS survey is published once per year; the flat file is the canonical release artifact. Building the dataset from individual series requests risks mixing observations from different release dates if any series was revised or re-released independently. The flat file eliminates this risk — every row in the file is from the same survey period.

**Column completeness.** The flat file includes fields that are not available as standalone series in the timeseries API, including employment count, wage percentiles (10th, 25th, 75th, 90th), and relative standard errors. These fields are needed for the wage distribution context the Power BI dashboard will display.

**Reproducibility.** A flat file download is deterministic given the URL and the survey year. A multi-request API pipeline is harder to reproduce exactly and introduces more failure modes (rate limiting, partial responses, session timeouts).

### Why the API is still demonstrated

The timeseries API is a real BLS data access pattern and a legitimate portfolio skill. The pipeline uses it for a targeted illustrative pull — five representative occupations, Employment Projections series, projected employment change percent — to achieve two goals:

1. Demonstrates correct API usage — authentication, request construction, JSON parsing, error handling, rate-limit awareness.
2. Produces an `api_ep_change_pct_check` column in the output that cross-validates API results against the flat file for the same occupations.

### Tradeoff acknowledged

Using the flat file means the pipeline requires an HTTP download of a ZIP file (~10–20 MB) rather than targeted API queries. This is slower to initialize but faster overall than 16+ sequential API calls. In a production environment with incremental update requirements, the API would be the right choice for pulling only changed series. For an annual-vintage analytical dataset, the flat file is appropriate.

---

## Alternatives Considered

| Option | Why Not Chosen |
|--------|---------------|
| API for all OEWS data | Query budget cost, consistency risk, missing columns |
| API for OEWS + EP both | Same issues; would require ~80+ API requests for full coverage |
| Scraping BLS website HTML | Fragile, not an authorized data access pattern |

---

## Consequences

- The `download_oews()` function in `pipeline.py` fetches and unzips the OEWS national file from a versioned BLS URL. If BLS changes the ZIP URL or the internal filename format in a future release, the URL and the filename detection logic in that function must be updated.
- The survey year is hardcoded as `2023` (OEWS May 2023). When the May 2024 data is released, update `OEWS_ZIP_URL` and `survey_year` in `pipeline.py`.
- The illustrative API pull (`pull_illustrative_api()`) will log warnings if the EP series IDs return no data. This does not block the pipeline — it degrades gracefully to flat-file-only output.
