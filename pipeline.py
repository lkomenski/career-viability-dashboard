"""
BLS Labor Market Data Pipeline
Career Viability Dashboard — Data Engineering Layer

Pulls OEWS wage data (flat file) and Employment Projections (flat file + BLS
timeseries API illustrative pull), joins at the SOC code level, computes
Career Viability Index scores, and exports a clean CSV for Power BI.

Data sources
  OEWS May 2023  : national flat file from BLS (ZIP download)
  EP 2024-2034   : Table 1.2 flat file from BLS (XLSX download)
  BLS API v2     : illustrative timeseries pull for five select occupations

Architecture decisions documented in docs/decisions/.
"""

import io
import logging
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

# ── Config ───────────────────────────────────────────────────────────────────

load_dotenv()

BLS_API_KEY = os.getenv("BLS_API_KEY", "")
BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# OEWS May 2023 national flat file (all occupations, all industries)
OEWS_ZIP_URL = "https://www.bls.gov/oes/special-requests/oesm23nat.zip"

# EP Table 1.2 — occupational projections and characteristics, 2024-2034.
# If the URL returns 403, download the file manually from the BLS page listed
# below and set EP_TABLE_LOCAL to the local path. The URL download will be
# skipped when EP_TABLE_LOCAL is set.
# Download page: https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm
EP_TABLE_URL = "https://www.bls.gov/emp/tables/ep_table_102.xlsx"
EP_TABLE_LOCAL = "data/Occupation.xlsx"

OUTPUT_DIR = Path("output")
OUTPUT_CSV = OUTPUT_DIR / "career_viability_data.csv"
LOG_FILE = OUTPUT_DIR / "pipeline.log"

# CVI weights (ADR-003). Wage 40%, Growth 35%, Demand 25%.
WAGE_WEIGHT = 0.40
GROWTH_WEIGHT = 0.35
DEMAND_WEIGHT = 0.25

# Five occupations used for the illustrative BLS API pull.
# One per broad sector — enough to demonstrate the API pattern without burning
# the daily query budget. The flat file remains the authoritative source.
ILLUSTRATIVE_SOCS = {
    "15-1252": "Software Developers",
    "29-1141": "Registered Nurses",
    "13-2011": "Accountants and Auditors",
    "11-1021": "General and Operations Managers",
    "25-2021": "Elementary School Teachers, General",
}

# 2018 SOC major group labels (2-digit prefix → name)
SOC_MAJOR_GROUPS = {
    "11": "Management",
    "13": "Business and Financial Operations",
    "15": "Computer and Mathematical",
    "17": "Architecture and Engineering",
    "19": "Life, Physical, and Social Science",
    "21": "Community and Social Service",
    "23": "Legal",
    "25": "Educational Instruction and Library",
    "27": "Arts, Design, Entertainment, Sports, and Media",
    "29": "Healthcare Practitioners and Technical",
    "31": "Healthcare Support",
    "33": "Protective Service",
    "35": "Food Preparation and Serving Related",
    "37": "Building and Grounds Cleaning and Maintenance",
    "39": "Personal Care and Service",
    "41": "Sales and Related",
    "43": "Office and Administrative Support",
    "45": "Farming, Fishing, and Forestry",
    "47": "Construction and Extraction",
    "49": "Installation, Maintenance, and Repair",
    "51": "Production",
    "53": "Transportation and Material Moving",
}

# ── Logging ──────────────────────────────────────────────────────────────────

OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="w"),
    ],
)
log = logging.getLogger(__name__)


# ── Section 1: BLS Timeseries API ────────────────────────────────────────────
#
# The BLS Public Data API v2 accepts up to 50 series IDs per request (with a
# registered key) and returns annual or monthly observations as JSON.
#
# EP series ID format for national detailed-occupation projections:
#   EP  = Employment Projections program
#   U   = not seasonally adjusted
#   10  = national, all workers
#   OOOC = detailed occupation classification
#   {6-digit SOC without hyphen}
#   {measure}: 01=employment level, 02=change (number), 03=change (percent)
#
# Series IDs can be verified at: https://data.bls.gov/cgi-bin/surveymost?ep


def build_ep_series_id(soc_code: str, measure: str = "03") -> str:
    """Return the BLS EP series ID for a SOC code and measure code."""
    soc_digits = soc_code.replace("-", "")
    return f"EPU10OOOC{soc_digits}{measure}"


def pull_bls_api(
    series_ids: list,
    start_year: int = 2023,
    end_year: int = 2023,
) -> pd.DataFrame:
    """
    POST to the BLS timeseries API and return a tidy DataFrame.
    Columns: series_id, year, period, value, footnotes.

    Returns an empty DataFrame if the request fails or no data comes back.
    Logs a warning per series that returns no observations — this usually
    means the series ID is invalid or the data is suppressed.
    """
    if not series_ids:
        return pd.DataFrame()

    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if BLS_API_KEY:
        payload["registrationkey"] = BLS_API_KEY
    else:
        log.warning("BLS_API_KEY not set — using unregistered tier (25 queries/day limit)")

    log.info(f"BLS API: requesting {len(series_ids)} series ({start_year}–{end_year})")

    try:
        resp = requests.post(
            BLS_API_URL,
            json=payload,
            headers={"Content-type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error(f"BLS API request failed: {exc}")
        return pd.DataFrame()

    result = resp.json()
    status = result.get("status", "")
    if status != "REQUEST_SUCCEEDED":
        messages = result.get("message", [])
        log.warning(f"BLS API status '{status}': {messages}")
        return pd.DataFrame()

    rows = []
    for series in result.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        data = series.get("data", [])
        if not data:
            log.warning(f"  No data for series {sid} — check ID validity or data availability")
            continue
        for obs in data:
            raw_val = obs.get("value", "")
            rows.append(
                {
                    "series_id": sid,
                    "year": int(obs["year"]),
                    "period": obs.get("period", ""),
                    "value": float(raw_val) if raw_val not in ("", "-") else None,
                    "footnotes": "; ".join(
                        f.get("text", "") for f in obs.get("footnotes", []) if f.get("text")
                    ),
                }
            )
        log.info(f"  {sid}: {len(data)} observation(s)")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Section 2: OEWS Flat File ─────────────────────────────────────────────────
#
# The OEWS national flat file covers ~800 detailed occupations with median
# annual wage, employment count, and wage percentiles. It is more reliable
# than pulling individual OEWS series via the API because the flat file
# guarantees a consistent vintage for all occupations in a single download.
#
# BLS suppresses wages when they cannot be disclosed:
#   '#'  = wage not available (occupation pays hourly only, or too few workers)
#   '*'  = wage below lowest published threshold
# These records are flagged rather than dropped so they appear in Power BI with
# a clear note. Suppressed wages are excluded from CVI ranking.


def download_oews(url: str = OEWS_ZIP_URL) -> pd.DataFrame:
    """
    Download the OEWS national ZIP, extract the Excel workbook, and return
    a clean DataFrame of detailed occupations with wage and employment fields.
    """
    log.info("Downloading OEWS May 2023 national flat file…")
    # BLS returns 403 for requests without a browser User-Agent header.
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=180)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"OEWS download failed: {exc}") from exc

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # The target file is identified by 'national' in the filename
        candidates = [n for n in zf.namelist() if "national" in n.lower() and n.endswith(".xlsx")]
        if not candidates:
            candidates = [n for n in zf.namelist() if n.endswith(".xlsx")]
        if not candidates:
            raise FileNotFoundError(f"No Excel file in OEWS ZIP. Contents: {zf.namelist()}")

        target = candidates[0]
        log.info(f"  Reading: {target}")
        with zf.open(target) as fh:
            raw = pd.read_excel(fh, dtype=str)

    raw.columns = raw.columns.str.strip().str.upper()
    log.info(f"  Raw shape: {raw.shape}  Columns: {list(raw.columns[:8])}…")

    # Keep only detailed-occupation rows (not aggregate major/minor group totals)
    if "O_GROUP" in raw.columns:
        df = raw[raw["O_GROUP"].str.strip().str.lower() == "detailed"].copy()
    else:
        # Fallback: detailed SOC codes match XX-XXXX exactly
        df = raw[raw["OCC_CODE"].str.strip().str.match(r"^\d{2}-\d{4}$", na=False)].copy()

    log.info(f"  Detailed occupations: {len(df)}")

    # Flag suppression before coercing to numeric
    suppressed = df["A_MEDIAN"].isin(["#", "*"])
    df["wage_suppressed"] = suppressed

    rename = {
        "OCC_CODE": "soc_code",
        "OCC_TITLE": "occupation_title",
        "TOT_EMP": "employment_count",
        "A_MEDIAN": "median_annual_wage",
        "A_PCT25": "wage_25th_pct",
        "A_PCT75": "wage_75th_pct",
    }
    available = {k: v for k, v in rename.items() if k in df.columns}
    df = df[list(available.keys()) + ["wage_suppressed"]].rename(columns=available)

    for col in ["employment_count", "median_annual_wage", "wage_25th_pct", "wage_75th_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["soc_code"] = df["soc_code"].str.strip()
    df["survey_year"] = 2023

    log.info(f"  Suppressed wages: {suppressed.sum()}")
    return df.reset_index(drop=True)


# ── Section 3: Employment Projections Flat File ───────────────────────────────
#
# BLS EP Table 1.2 covers projected employment 2024-2034 for ~800 detailed
# occupations. The key fields for CVI are:
#   employment_change_pct   — 10-year percent growth (CVI Growth signal)
#   annual_openings         — average annual projected openings from both growth
#                             and replacement needs (CVI Demand signal; see ADR-002)
#
# The Excel file has multi-row BLS formatting headers. The SOC code column start
# row is detected dynamically rather than hardcoded, making the parser robust to
# minor BLS file format changes between vintages.


def download_ep(url: str = EP_TABLE_URL, local_path: str = EP_TABLE_LOCAL) -> pd.DataFrame:
    """
    Load BLS EP Table 1.2 and return a clean DataFrame of detailed
    occupations with growth and openings projections for 2024-2034.

    If local_path is set, reads from disk and skips the network request.
    Otherwise downloads from url. Set EP_TABLE_LOCAL in config if the URL
    returns 403 — download the file manually from the BLS page in the comment
    above EP_TABLE_URL and point local_path at it.
    """
    if local_path:
        log.info(f"Reading Employment Projections from local file: {local_path}")
        raw_bytes = Path(local_path).read_bytes()
    else:
        log.info("Downloading Employment Projections Table 1.2 (2024-2034)…")
        headers = {"User-Agent": "Mozilla/5.0 (compatible; research-pipeline/1.0)"}
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"EP download failed: {exc}\n"
                "Download the file manually from:\n"
                "  https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm\n"
                "Then set EP_TABLE_LOCAL in pipeline.py to the local file path."
            ) from exc
        raw_bytes = resp.content

    # The BLS EP file has multiple sheets (cover, notes, multiple tables).
    # Scan every sheet to find the one containing detailed SOC codes.
    # Major-group summary codes (XX-0000) are excluded by requiring the
    # 4-digit part to start with 1-9; only detailed occupations match.
    soc_pattern = r"^\d{2}-[1-9]\d{3}$"
    xf = pd.ExcelFile(io.BytesIO(raw_bytes))
    log.info(f"  EP file sheets: {xf.sheet_names}")

    target_sheet: str | None = None
    data_start_row: int | None = None

    for sheet in xf.sheet_names:
        probe = xf.parse(sheet, dtype=str, header=None)
        for row_num, (_, row) in enumerate(probe.iterrows()):
            if any(isinstance(v, str) and pd.Series([v]).str.match(soc_pattern).any() for v in row):
                target_sheet = str(sheet)
                data_start_row = row_num
                break
        if target_sheet is not None:
            break

    if target_sheet is None or data_start_row is None:
        raise ValueError(
            f"No sheet with SOC codes found in EP file. Sheets present: {xf.sheet_names}\n"
            "The BLS file format may have changed."
        )

    log.info(f"  SOC data found in sheet: '{target_sheet}'")

    # The row immediately above the first data row is the column header
    header_row = max(0, data_start_row - 1)
    log.info(f"  EP header row: {header_row}, first data row: {data_start_row}")

    df = pd.read_excel(io.BytesIO(raw_bytes), sheet_name=target_sheet, dtype=str, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    # Identify the SOC code column
    soc_col = next(
        (c for c in df.columns if df[c].astype(str).str.strip().str.match(soc_pattern).any()),
        None,
    )
    if soc_col is None:
        raise ValueError("Could not identify SOC code column in EP file.")

    df = df[df[soc_col].astype(str).str.strip().str.match(soc_pattern, na=False)].copy()
    log.info(f"  EP detailed occupations: {len(df)}")

    # Log actual column names so the position mapping can be verified and corrected
    cols = list(df.columns)
    soc_idx = cols.index(soc_col)
    def col_at(offset: int):
        idx = soc_idx + offset
        return cols[idx] if 0 <= idx < len(cols) else None

    # Column layout for EP Table 1.2, 2024-34 vintage (confirmed by position audit):
    #   index 0  = occupation title (one position BEFORE the SOC column)
    #   index 1  = SOC code
    #   index 2  = Summary/Detail indicator
    #   index 3  = employment_2024
    #   index 4  = employment_2034
    #   index 5-6 = unknown BLS columns (skipped)
    #   index 7  = employment_change_number
    #   index 8  = employment_change_pct
    #   index 9  = unknown
    #   index 10 = annual_openings
    #   index 11 = median_annual_wage_ep (bonus cross-check column)
    #   index 12 = typical_entry_education
    rename = {soc_col: "soc_code"}
    offsets = {
        -1: "occupation_title_ep",
        2:  "employment_2024",
        3:  "employment_2034",
        6:  "employment_change_number",
        7:  "employment_change_pct",
        9:  "annual_openings",
        11: "typical_entry_education",
    }
    for offset, field in offsets.items():
        c = col_at(offset)
        if c:
            rename[c] = field

    df = df[[c for c in rename if c in df.columns]].rename(columns=rename)

    for col in ["employment_2024", "employment_2034", "employment_change_number",
                "employment_change_pct", "annual_openings"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["soc_code"] = df["soc_code"].str.strip()
    df["projection_period"] = "2024-2034"

    return df.reset_index(drop=True)


# ── Section 4: Illustrative BLS API Pull ─────────────────────────────────────
#
# Projected employment change (%) is requested for five representative SOC codes
# via the BLS timeseries API. This serves two purposes:
#   1. Demonstrates API authentication, request construction, and JSON parsing.
#   2. Produces an 'api_check' column that cross-validates the API result against
#      the flat file value for the same occupation.
#
# If the API returns no data (bad series ID, suppression, or rate limit), the
# warning is logged and execution continues. The flat file covers all occupations.


def pull_illustrative_api(soc_map: dict | None = None) -> pd.DataFrame:
    """
    Pull projected employment change (%) via the BLS API for ILLUSTRATIVE_SOCS.
    Returns a DataFrame with soc_code and api_ep_change_pct_check columns,
    or an empty DataFrame if the API call fails entirely.
    """
    if soc_map is None:
        soc_map = ILLUSTRATIVE_SOCS

    series_ids = [build_ep_series_id(soc, measure="03") for soc in soc_map]
    log.info(f"Illustrative API pull — series IDs: {series_ids}")

    api_raw = pull_bls_api(series_ids, start_year=2023, end_year=2023)

    if api_raw.empty:
        log.warning("Illustrative API pull returned no data. Flat file is sole EP source.")
        return pd.DataFrame()

    # EP annual projections use period 'A01' (annual)
    annual = api_raw[api_raw["period"] == "A01"].copy()
    if annual.empty:
        # Some EP series use period 'Q05' or other codes depending on vintage.
        # Fall back to most recent observation per series.
        annual = api_raw.sort_values("year", ascending=False).drop_duplicates("series_id").copy()
        log.warning("API result had no 'A01' period — using most recent observation per series")

    # Reconstruct SOC code from series ID: strip prefix EPU10OOOC and suffix (last 2 chars)
    annual["soc_digits"] = annual["series_id"].str[len("EPU10OOOC"):-2]
    annual["soc_code"] = annual["soc_digits"].str[:2] + "-" + annual["soc_digits"].str[2:]
    annual = annual.rename(columns={"value": "api_ep_change_pct_check"})

    result = annual[["soc_code", "api_ep_change_pct_check"]].copy()
    log.info(f"  API check values retrieved for {len(result)} occupation(s)")
    return result


# ── Section 5: Join and SOC Mismatch Detection ───────────────────────────────
#
# OEWS uses 2018 SOC codes. EP 2024-2034 also targets 2018 SOC, but the two
# programs may still diverge: EP aggregates some occupations that OEWS publishes
# separately, and vice versa. Any SOC code that appears in one file but not the
# other is flagged here and surfaced as soc_mismatch_flag in the output.
#
# Mismatches are expected — they are not errors. Document them in the dashboard.


def join_and_flag_mismatches(oews: pd.DataFrame, ep: pd.DataFrame) -> pd.DataFrame:
    """
    Left-join OEWS to EP on soc_code. OEWS is the left (base) table so every
    wage record appears in the output even if EP has no matching projection.
    Log all SOC codes present in one dataset but absent from the other.
    """
    oews_codes = set(oews["soc_code"])
    ep_codes = set(ep["soc_code"])

    oews_only = sorted(oews_codes - ep_codes)
    ep_only = sorted(ep_codes - oews_codes)

    if oews_only:
        log.warning(f"SOC MISMATCH — {len(oews_only)} code(s) in OEWS but not EP:")
        for code in oews_only[:30]:
            log.warning(f"  OEWS-only: {code}")
        if len(oews_only) > 30:
            log.warning(f"  … and {len(oews_only) - 30} more. Full list in output CSV (soc_mismatch_flag=True).")

    if ep_only:
        log.warning(f"SOC MISMATCH — {len(ep_only)} code(s) in EP but not OEWS:")
        for code in ep_only[:30]:
            log.warning(f"  EP-only: {code}")
        if len(ep_only) > 30:
            log.warning(f"  … and {len(ep_only) - 30} more.")

    merged = oews.merge(ep, on="soc_code", how="left")
    merged["soc_in_ep"] = merged["soc_code"].isin(ep_codes)
    merged["soc_mismatch_flag"] = ~merged["soc_in_ep"]

    matched = merged["soc_in_ep"].sum()
    log.info(f"Join complete: {len(merged)} rows — {matched} matched, {merged['soc_mismatch_flag'].sum()} unmatched")
    return merged


# ── Section 6: Percentile Ranks ───────────────────────────────────────────────
#
# Percentile rank normalizes each input to a 0–100 scale regardless of its
# original unit. This is necessary because the three CVI inputs have
# incompatible units (dollars, percent, headcount); direct averaging is not valid. Ranking against the full occupation set makes the CVI a relative
# score — it tells you where an occupation stands in the field, not what its
# absolute values are.
#
# Suppressed wages receive NaN rank and are excluded from CVI. This is
# intentional: a missing data point should not drag down or inflate a score.


def add_percentile_ranks(df: pd.DataFrame) -> pd.DataFrame:
    """Add wage_pct_rank, growth_pct_rank, and demand_pct_rank columns (0–100)."""

    def pct_rank(series: pd.Series) -> pd.Series:
        return series.rank(pct=True, na_option="keep") * 100

    # Wage: exclude suppressed values from ranking
    if "wage_suppressed" in df.columns:
        wage_valid = df["median_annual_wage"].where(~df["wage_suppressed"])
    else:
        wage_valid = df["median_annual_wage"]
    df["wage_pct_rank"] = pct_rank(wage_valid).round(2)

    growth_col = df["employment_change_pct"] if "employment_change_pct" in df.columns else pd.Series(np.nan, index=df.index)
    df["growth_pct_rank"] = pct_rank(growth_col).round(2)

    demand_col = df["annual_openings"] if "annual_openings" in df.columns else pd.Series(np.nan, index=df.index)
    df["demand_pct_rank"] = pct_rank(demand_col).round(2)

    return df


# ── Section 7: Career Viability Index ────────────────────────────────────────
#
# CVI = 0.40 × wage_pct_rank + 0.35 × growth_pct_rank + 0.25 × demand_pct_rank
#
# Occupations with any null rank component receive a null CVI and a flag.
# Missing values are not imputed — a partial score is misleading because it
# would rank an occupation against peers that have all three components scored.
# (See ADR-003 for weighting rationale.)


def add_cvi_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Career Viability Index and a completeness flag."""
    df["cvi_score"] = (
        WAGE_WEIGHT * df["wage_pct_rank"]
        + GROWTH_WEIGHT * df["growth_pct_rank"]
        + DEMAND_WEIGHT * df["demand_pct_rank"]
    ).round(2)

    df["cvi_complete"] = (
        df["wage_pct_rank"].notna()
        & df["growth_pct_rank"].notna()
        & df["demand_pct_rank"].notna()
    )

    # Null out the score for incomplete records to prevent misleading ranks in Power BI
    df.loc[~df["cvi_complete"], "cvi_score"] = np.nan

    complete = int(df["cvi_complete"].sum())
    log.info(f"CVI: {complete} complete scores, {len(df) - complete} nulled (incomplete data)")
    return df


# ── Section 8: Occupation Group and Data Flags ────────────────────────────────


def add_occupation_group(df: pd.DataFrame) -> pd.DataFrame:
    """Derive the 2-digit SOC major group code and label from the SOC code."""
    df["soc_major_group_code"] = df["soc_code"].str[:2]
    df["soc_major_group"] = df["soc_major_group_code"].map(SOC_MAJOR_GROUPS).fillna("Other / Unknown")
    return df


def build_data_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compose a pipe-delimited data quality flag string for each row.
    Power BI can display this in a tooltip or filter on it.
    """
    parts = []
    if "wage_suppressed" in df.columns:
        parts.append(df["wage_suppressed"].map({True: "wage suppressed", False: ""}))
    if "soc_mismatch_flag" in df.columns:
        parts.append(df["soc_mismatch_flag"].map({True: "no EP match", False: ""}))
    if "cvi_complete" in df.columns:
        parts.append((~df["cvi_complete"]).map({True: "incomplete CVI", False: ""}))

    if not parts:
        df["data_flag"] = ""
        return df

    flag_df = pd.concat(parts, axis=1)
    flag_df.columns = range(len(parts))
    df["data_flag"] = (
        flag_df.apply(lambda row: " | ".join(v for v in row if v), axis=1)
    )
    return df


# ── Section 9: Export ─────────────────────────────────────────────────────────
#
# Column order is designed for direct import into Power BI with no further
# transformation needed in Power Query. Identifiers first, then source measures,
# then derived/calculated fields, then flags and metadata.


def export_csv(df: pd.DataFrame, path: Path = OUTPUT_CSV) -> None:
    """Write the final dataset to CSV."""
    col_order = [
        # Identifiers
        "soc_code",
        "occupation_title",
        "soc_major_group_code",
        "soc_major_group",
        # OEWS source measures
        "median_annual_wage",
        "wage_25th_pct",
        "wage_75th_pct",
        "employment_count",
        # EP source measures
        "employment_2024",
        "employment_2034",
        "employment_change_number",
        "employment_change_pct",
        "annual_openings",
        "typical_entry_education",
        # API cross-check (illustrative pull)
        "api_ep_change_pct_check",
        # Derived ranks (inputs to CVI)
        "wage_pct_rank",
        "growth_pct_rank",
        "demand_pct_rank",
        # CVI
        "cvi_score",
        "cvi_complete",
        # Quality flags
        "wage_suppressed",
        "soc_mismatch_flag",
        "data_flag",
        # Metadata
        "survey_year",
        "projection_period",
    ]
    final_cols = [c for c in col_order if c in df.columns]
    df[final_cols].to_csv(path, index=False)
    log.info(f"Exported {len(df)} rows, {len(final_cols)} columns -> {path}")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> pd.DataFrame:
    log.info("=" * 60)
    log.info("Career Viability Pipeline  START")
    log.info("=" * 60)

    # 1. Ingest
    oews = download_oews()
    ep = download_ep()
    api_sample = pull_illustrative_api()

    # 2. Join
    df = join_and_flag_mismatches(oews, ep)

    # 3. Attach API cross-check values for the five illustrative occupations
    if not api_sample.empty:
        df = df.merge(api_sample, on="soc_code", how="left")
        log.info("API cross-check column attached")

    # 4. Derive calculated fields
    df = add_percentile_ranks(df)
    df = add_cvi_score(df)
    df = add_occupation_group(df)
    df = build_data_flags(df)

    # 5. Export
    export_csv(df)

    log.info("=" * 60)
    log.info("Career Viability Pipeline  COMPLETE")
    log.info("=" * 60)
    return df


if __name__ == "__main__":
    main()
