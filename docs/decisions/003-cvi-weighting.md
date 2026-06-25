# ADR-003: Career Viability Index Weighting (40 / 35 / 25)

**Status:** Accepted  
**Date:** 2025-06  
**Decider:** Leena Komenski

---

## Context

The Career Viability Index (CVI) is a composite score that combines three percentile-ranked signals into a single number per occupation. The score is only meaningful if the weights are defensible — not just chosen arbitrarily, and not naively equal without justification.

Three inputs go into the CVI:

- **Wage signal** — percentile rank of median annual wage relative to all occupations
- **Growth signal** — percentile rank of 10-year projected employment change (%)
- **Demand signal** — percentile rank of projected annual openings

The weights must sum to 1.0. Any weighting is a modeling choice, not a mathematical truth. What matters is that the choice is reasoned and can be explained.

---

## Decision

**Wage: 40%, Growth: 35%, Demand: 25%**

Implemented as:

```
CVI = 0.40 × wage_pct_rank + 0.35 × growth_pct_rank + 0.25 × demand_pct_rank
```

---

## Rationale

### Wage at 40% — highest weight

Wage is the most directly observable and most reliably measured signal. It is a realized market outcome from an actual survey of employers, not a model output or a projection. It reflects the cumulative effect of supply and demand for labor in that occupation — education requirements, skill scarcity, economic sector health, and compensation culture are all embedded in the wage.

From a career decision standpoint, wage is also the most immediately actionable signal. A job seeker weighing two career paths can directly observe the wage gap between them. Growth and demand are relevant for long-term positioning, but wage determines near-term financial security.

Higher weight also reflects higher data quality: OEWS wages have published relative standard errors and are based on a large-sample annual survey. EP projections carry 10-year uncertainty that OEWS wages do not.

### Growth at 35% — second highest weight

The 10-year projected employment change rate is the most forward-looking and career-relevant of the three signals. A career choice is a long-horizon decision. An occupation that is declining in total employment is a riskier career path even if current wages are high, because the future labor market for that occupation is contracting.

Growth receives a slightly lower weight than wage because:

1. Projections carry more uncertainty than realized wages. BLS 10-year projections have historically had meaningful error rates, particularly for technology-adjacent occupations.
2. A large percent change on a small base does not mean many opportunities — a 30% growth rate on 5,000 workers adds fewer net positions than a 5% growth rate on 500,000 workers. The demand signal (annual openings) partially corrects for this by counting absolute opportunity volume.

### Demand at 25% — lowest weight

Annual openings signal the volume of entry opportunities per year, which is directly relevant to a job seeker. However, it receives the lowest weight for two reasons:

**Correlation with occupation size.** Large occupations generate more replacement openings even with zero growth, simply because more workers retire or change careers each year. This means demand partially overlaps with the wage signal (large, well-established occupations tend to have above-median wages) and with the growth signal (occupations projected to grow will also have growth-driven openings). The 25% weight limits double-counting.

**Same projection period as growth.** Annual openings come from the same EP projection file as the growth rate. They are not independent observations — they are two outputs from the same BLS modeling exercise. Weighting them equally would give EP projections 60% combined weight versus 40% for realized OEWS wages, which inverts the reliability relationship.

### Equal weighting was considered and rejected

Weighting all three at 33.3% would make the CVI simpler to explain, but it would weight projected demand at the same level as realized wages despite the demand signal having:
- Lower data quality (projected, not measured)
- Correlation with the third signal

Equal weighting is harder to defend analytically than the asymmetric weights chosen here.

---

## User-Adjustable Weights (Second Pass)

The static weights above are implemented in Python and baked into the output CSV. In the second pass of dashboard development, the Power BI model will include three disconnected parameter tables (Wage Weight, Growth Weight, Demand Weight) with slicers from 0 to 100. The DAX measure will normalize the selected weights to sum to 1.0:

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

This makes the weighting transparent to dashboard users and turns the CVI into an interactive analytical tool rather than a fixed ranking.

---

## Consequences

- The weights are constants in `pipeline.py` (`WAGE_WEIGHT`, `GROWTH_WEIGHT`, `DEMAND_WEIGHT`). Changing them requires re-running the pipeline and reloading the CSV in Power BI.
- The static CVI in the CSV (`cvi_score`) and the dynamic DAX version (`CVI Dynamic`) will produce different rankings when the user adjusts the sliders. Both are valid; the static version is the default.
- Dashboard documentation should clearly state the default weights and invite users to adjust them. This converts a potential criticism ("why these weights?") into a feature.
