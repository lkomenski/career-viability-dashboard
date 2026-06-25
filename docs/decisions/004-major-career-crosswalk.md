# ADR-004: Major-to-Career Mapping Requires a Supplemental CIP-SOC Crosswalk

**Status:** Accepted  
**Date:** 2025-06  
**Decider:** Leena Komenski

---

## Context

One of the four dashboard views is a major-to-career mapping: given a college major, which occupations are viable paths, and how do they score on the CVI? The project brief asked us to determine whether this mapping is feasible from BLS data alone.

BLS publishes occupation data organized by SOC (Standard Occupational Classification) codes. It does not publish a native crosswalk from CIP (Classification of Instructional Programs — the federal taxonomy for college majors) to SOC occupations.

---

## Decision

The major-to-career mapping **requires a supplemental CIP-SOC crosswalk table**. This table cannot be derived from BLS data alone. It will be sourced from the National Center for Education Statistics (NCES) and maintained as a reference file in this repository.

---

## Rationale

BLS EP Table 1.2 includes a "Typical Entry-Level Education" field per occupation (e.g., "Bachelor's degree," "Associate's degree," "No formal educational credential"). This field describes the level of education typically required — it does not describe which field of study. You cannot derive "Software Developers typically hold CS degrees" from BLS data.

The NCES publishes the CIP-to-SOC crosswalk as part of the Integrated Postsecondary Education Data System (IPEDS) framework. This crosswalk maps CIP codes (college major classifications) to SOC codes (occupation classifications) and is designed precisely for this use case. It is available for public download.

---

## What the Crosswalk Table Looks Like

The supplemental table (`data/cip_soc_crosswalk.csv`) has the following structure:

| Column | Type | Example | Notes |
|--------|------|---------|-------|
| `cip_code` | string | `11.0101` | 6-digit CIP code |
| `cip_title` | string | `Computer and Information Sciences, General` | Major name per NCES taxonomy |
| `cip_broad_category` | string | `Computer and Information Sciences` | 2-digit CIP family |
| `soc_code` | string | `15-1252` | Foreign key to occupation table |
| `relationship_strength` | string | `Primary` | `Primary` or `Related` |

**Relationship strength** distinguishes direct pathways (a CS degree → Software Developer) from adjacent ones (a CS degree → Operations Research Analyst). This field supports filtering in the dashboard.

---

## Power BI Data Model Implications

The crosswalk creates a many-to-many relationship between majors and occupations, which Power BI handles via a bridge table pattern:

```
Majors (cip_code PK)
    ↓
CIP_SOC_Bridge (cip_code, soc_code)
    ↓
Occupations (soc_code PK)
```

In Power BI, set both relationships to single-direction filtering (from Majors → Bridge and from Occupations → Bridge). Do not use bidirectional filtering — it creates ambiguous filter contexts in DAX. Use TREATAS() or CROSSFILTER() in DAX measures when you need to propagate filters in both directions.

---

## Limitations and Disclosure Language

The following limitations must be disclosed in the dashboard:

**1. The crosswalk reflects typical pathways, not guarantees.**  
A computer science major can become a financial analyst, a technical writer, or an operations manager. The CIP-SOC crosswalk captures modal career paths — where graduates typically end up — not the full range of possible outcomes.

**2. Coverage is incomplete for general majors.**  
Broad or interdisciplinary majors (e.g., "Liberal Arts," "General Studies") map to many SOC codes with weak relationship strength. The dashboard should surface these as "broad path" majors and avoid implying the mapping is precise.

**3. The crosswalk is not updated annually.**  
NCES updates the CIP taxonomy periodically (major updates occurred in 2000, 2010, and 2020). SOC codes were revised in 2018. The crosswalk may not reflect the most recent SOC or CIP vintages. Document the crosswalk version in the data sources section of the dashboard.

**4. Suggested disclosure language for the dashboard:**  
> *Major-to-career mappings are sourced from the NCES CIP-to-SOC crosswalk and reflect typical educational pathways into each occupation. They do not represent all possible career paths from a given major. Occupation scores reflect BLS labor market data, not major-specific outcomes.*

---

## Alternatives Considered

| Option | Why Not Chosen |
|--------|---------------|
| Use BLS EP "Typical Entry-Level Education" field alone | Field describes degree level, not field of study — cannot map majors |
| Manually build the crosswalk from scratch | Labor-intensive and subjective; NCES crosswalk is authoritative |
| Omit the major-to-career view | Eliminates a key analytical feature; NCES crosswalk solves the problem cleanly |
| Use O*NET's education/training data | O*NET is more detailed but requires a separate data source integration and adds complexity |

---

## Consequences

- A `data/` directory will hold `cip_soc_crosswalk.csv` as a versioned reference file. This file is committed to the repository (it is reference data, not generated output).
- The crosswalk must be loaded into Power BI as a separate table and related to the Occupations table via `soc_code`.
- If a major maps to occupations not present in the OEWS/EP dataset (suppressed or missing), those occupations will not appear in the major-to-career view. This is expected behavior and should be noted in the dashboard.
