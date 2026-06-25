# ADR-002: Use EP Annual Openings as the Demand Signal Instead of JOLTS

**Status:** Accepted  
**Date:** 2025-06  
**Decider:** Leena Komenski

---

## Context

The Career Viability Index requires three input signals: earning potential (wage), employment growth, and demand. The project brief listed JOLTS (Job Openings and Labor Turnover Survey) as a potential third signal, to be included only if it could be cleanly joined to occupation-level data.

Three candidates were evaluated for the demand signal:

1. **JOLTS job openings** — published monthly by BLS
2. **OEWS total employment count** — published annually by BLS with the wage data
3. **EP annual projected openings** — published by the Employment Projections program as part of Table 1.2

---

## Decision

Use **EP annual projected openings** (`annual_openings` field from EP Table 1.2) as the demand signal.

---

## Rationale

### Why JOLTS was eliminated

JOLTS publishes job openings at the **industry sector** level (e.g., "Professional and Business Services," "Health Care and Social Assistance"). It does not break down job openings by SOC occupation code.

Joining JOLTS to occupation-level data would require a multi-step industry-to-occupation crosswalk. BLS publishes an industry-occupation employment matrix that maps industries to occupations by share of employment, which could be used to apportion JOLTS openings to SOC codes. However:

- The apportionment is a modeled estimate, not a direct observation.
- The result is sensitive to the assumed industry-occupation shares.
- It introduces a two-join chain (JOLTS → industry matrix → SOC) where each step adds error.
- The output would be difficult to explain and harder to defend in an interview than a direct BLS observation.

The project brief explicitly stated: *"do not force it if the join is messy."* The JOLTS-to-SOC join is messy. It was eliminated.

### Why OEWS total employment was the fallback

OEWS includes total employment (`TOT_EMP`) for each occupation. A large occupation with high employment signals market demand — there are more roles to fill, more hiring events, and more entry points for job seekers. This is a valid demand proxy and requires no additional join.

The limitation is that `TOT_EMP` is a stock measure, not a flow measure. It counts how many people are currently employed in an occupation, not how many positions are being filled. A large, stable occupation with minimal turnover scores identically to a large, high-turnover occupation, even though the latter offers far more entry opportunities.

### Why EP annual openings is the best choice

EP Table 1.2 publishes "occupational openings" — the projected average annual number of positions that need to be filled each year over the 2023-2033 projection period. This combines two components:

- **Growth openings:** new positions created by net employment increase
- **Replacement openings:** positions vacated by retirement, career change, or other separation

This is a flow measure, not a stock measure. It directly answers the question a job seeker cares about: *how many opportunities will open up per year in this occupation?* It is at the SOC code grain, it requires no crosswalk, and it comes from the same flat file as the growth rate — which means it is already being downloaded and the join is free.

### Correlation caveat

Annual openings correlate with occupation size. Larger occupations generate more replacement openings by volume, so this signal has a mild size bias. The 25% weight in the CVI (see ADR-003) mitigates this, and the bias is disclosed in the dashboard.

---

## Alternatives Considered

| Option | Grain | Join Required | Flow or Stock | Decision |
|--------|-------|---------------|---------------|----------|
| JOLTS job openings | Industry sector | Multi-step crosswalk | Flow | Eliminated — messy join |
| OEWS total employment | SOC code | None (already loaded) | Stock | Runner-up — valid but weaker |
| EP annual openings | SOC code | None (same file as growth) | Flow | Selected |

---

## Consequences

- `annual_openings` is sourced from EP Table 1.2. If BLS changes the column position or label in a future EP release, the column-position detection logic in `download_ep()` will need adjustment.
- The CVI demand signal is a projected forward-looking measure (2023-2033), while the wage signal is a realized backward-looking measure (May 2023). This is intentional — a career viability index should be sensitive to both current market conditions and expected future demand. Document this asymmetry in the dashboard.
- If JOLTS eventually publishes occupation-level data (BLS has been moving in this direction), this decision should be revisited.
