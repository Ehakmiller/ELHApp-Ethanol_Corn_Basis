#!/usr/bin/env python
"""
Audit old corn basis files for possible SQL backfill.

This script is intentionally read-only against the production SQLite database.
It writes review outputs and a local staging SQLite database under
backfill_audit/ so old files can be inspected before any production import.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_OLD_DIR = Path(
    r"C:\Users\ehakm\OneDrive\Documents\Ethanol Industry Data"
    r"\Corn Basis DataBase\Basis Data"
)
DEFAULT_DB_PATH = Path(
    r"C:\Users\ehakm\OneDrive\Documents\Python Code\Ethanol db"
    r"\Ethanol DB\ethanol_production.db"
)
DEFAULT_OUTPUT_DIR = Path("backfill_audit")
FILE_EXTENSIONS = {".csv", ".xls", ".xlsx", ".xlsm"}

CORE_FIELDS = [
    "date",
    "plant_id",
    "ownership",
    "plant_name",
    "city",
    "state",
    "latitude",
    "longitude",
    "basis",
    "flat_price",
    "contract",
    "delivery_month",
    "commodity",
]
OPTIONAL_FIELDS = [
    "capacity_mgy",
    "technology",
    "rail_lines",
    "corn_ci",
    "fiber_ci",
    "source_file",
]

FIELD_ALIASES = {
    "date": ["date", "basis date"],
    "plant_id": ["co id", "co_id", "epm", "epm_number", "plant_id"],
    "ownership": ["ownership", "company", "owner"],
    "plant_name": ["facility", "plant name", "plant", "name"],
    "city": ["city"],
    "state": ["state"],
    "latitude": ["epa latitude", "latitude", "lat"],
    "longitude": ["epa longitude", "longitude", "lon", "lng"],
    "basis": ["adj basis", "adj_basis", "normalized basis", "basis"],
    "flat_price": ["flat", "flat price", "flat_price"],
    "contract": ["contract", "contract month", "contract_month"],
    "delivery_month": ["del month", "delivery", "delivery month", "del_month"],
    "commodity": ["commodity"],
    "capacity_mgy": ["capacity (m gals)", "ethanol capacity", "capacity"],
    "technology": ["technology"],
    "rail_lines": ["rail lines", "rail"],
    "corn_ci": ["ci score          corn (009)", "corn ci", "corn_ci"],
    "fiber_ci": ["ci score            corn fiber (012)", "fiber ci", "fiber_ci"],
}


@dataclass
class SheetRead:
    sheet_name: str
    df: pd.DataFrame
    header_row: int | None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit old basis files for staging backfill.")
    parser.add_argument("--old-dir", default=str(DEFAULT_OLD_DIR), help="Folder containing old basis files.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Production SQLite DB path, read-only.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Audit output folder.")
    parser.add_argument("--sample-rows", type=int, default=0, help="Optional row limit per sheet for faster debugging.")
    return parser.parse_args()


def norm_name(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\n", " ")
    return text


def canonical_columns(df: pd.DataFrame) -> dict[str, str]:
    by_norm = {norm_name(col): str(col) for col in df.columns}
    found: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in by_norm:
                found[field] = by_norm[alias]
                break
    return found


def infer_date_from_filename(path: Path) -> str | None:
    match = re.search(r"(\d{6})", path.stem)
    if not match:
        return None
    raw = match.group(1)
    for fmt in ("%m%d%y", "%y%m%d"):
        parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
        if pd.notna(parsed):
            return parsed.strftime("%Y-%m-%d")
    return None


def parse_date_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def parse_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "no basis", "na", "n/a"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("$", "").replace(",", "")
    parsed = pd.to_numeric(text, errors="coerce")
    if pd.isna(parsed):
        return None
    num = float(parsed)
    return -abs(num) if negative else num


def clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_state(value: Any) -> str | None:
    text = clean_text(value)
    return text.upper() if text else None


def normalize_delivery_month(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.notna(parsed):
        return parsed.strftime("%b %y")
    contract_like = re.fullmatch(r"([A-Z])([A-Z])?(\d{1,2})", text.upper().replace("(", "").replace(")", ""))
    month_lookup = {
        "F": "Jan",
        "G": "Feb",
        "H": "Mar",
        "J": "Apr",
        "K": "May",
        "M": "Jun",
        "N": "Jul",
        "Q": "Aug",
        "U": "Sep",
        "V": "Oct",
        "X": "Nov",
        "Z": "Dec",
    }
    if contract_like:
        code = contract_like.group(2) or contract_like.group(1)
        year = contract_like.group(3)
        if code in month_lookup:
            return f"{month_lookup[code]} {int(year):02d}"
    month_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{2,4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        month = month_match.group(1).title()[:3]
        year = month_match.group(2)[-2:]
        return f"{month} {year}"
    return text


def read_csv_file(path: Path, sample_rows: int) -> list[SheetRead]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            df = pd.read_csv(path, nrows=sample_rows or None, encoding=encoding)
            return [SheetRead("CSV", clean_dataframe(df), 0)]
        except Exception:
            continue
    try:
        df = pd.read_csv(path, nrows=sample_rows or None, encoding_errors="ignore")
        return [SheetRead("CSV", clean_dataframe(df), 0)]
    except Exception as exc:
        return [SheetRead("CSV", pd.DataFrame(), None, str(exc))]


def read_excel_file(path: Path, sample_rows: int) -> list[SheetRead]:
    try:
        xl = pd.ExcelFile(path)
    except Exception as exc:
        return [SheetRead("", pd.DataFrame(), None, str(exc))]
    sheets: list[SheetRead] = []
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(path, sheet_name=sheet, header=0, nrows=sample_rows or None)
            df = clean_dataframe(df)
            cols = canonical_columns(df)
            score = len(set(cols) & {"basis", "plant_name", "city", "state", "commodity", "contract"})
            if score >= 3:
                sheets.append(SheetRead(sheet, df, 0))
                continue
            best: SheetRead | None = SheetRead(sheet, df, 0)
            best_score = score
            last_error = None
        except Exception as exc:
            best = None
            best_score = -1
            last_error = str(exc)

        for header_row in range(1, 6):
            try:
                df = pd.read_excel(path, sheet_name=sheet, header=header_row, nrows=sample_rows or None)
                df = clean_dataframe(df)
                cols = canonical_columns(df)
                score = len(set(cols) & {"basis", "plant_name", "city", "state", "commodity", "contract"})
                if score > best_score:
                    best = SheetRead(sheet, df, header_row)
                    best_score = score
            except Exception as exc:
                last_error = str(exc)
        sheets.append(best if best is not None else SheetRead(sheet, pd.DataFrame(), None, last_error))
    return sheets


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all").copy()
    df.columns = [str(col).strip() for col in df.columns]
    return df


def read_old_file(path: Path, sample_rows: int) -> list[SheetRead]:
    if path.suffix.lower() == ".csv":
        return read_csv_file(path, sample_rows)
    return read_excel_file(path, sample_rows)


def load_plant_master(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query('SELECT * FROM "Corn_Processors"', conn)
    df["plant_id"] = df["EPM"].astype("string").str.strip()
    df["plant_name"] = df["Name"].astype("string").str.strip()
    df["city_norm"] = df["City"].astype("string").str.strip().str.lower()
    df["state_norm"] = df["State"].astype("string").str.strip().str.upper()
    df["name_norm"] = df["plant_name"].astype("string").str.lower()
    return df


def load_existing_keys(conn: sqlite3.Connection) -> set[tuple[str | None, str | None, str, str | None, str | None]]:
    df = pd.read_sql_query(
        """
        SELECT Epm_number, Date, Del_Month, Contract_Month
        FROM CornBasis
        """,
        conn,
    )
    keys = set()
    for row in df.to_dict("records"):
        keys.add(
            (
                parse_date_value(row.get("Date")),
                clean_text(row.get("Epm_number")),
                "Corn",
                normalize_delivery_month(row.get("Del_Month")),
                clean_text(row.get("Contract_Month")),
            )
        )
    return keys


def match_plant(row: dict[str, Any], plants: pd.DataFrame) -> tuple[str | None, str, float | None]:
    plant_id = clean_text(row.get("plant_id"))
    if plant_id:
        hit = plants[plants["plant_id"] == plant_id]
        if not hit.empty:
            return str(hit.iloc[0]["plant_id"]), "exact_id", 1.0

    name = norm_name(row.get("plant_name"))
    city = norm_name(row.get("city"))
    state = normalize_state(row.get("state"))
    if name and city and state:
        candidates = plants[(plants["city_norm"] == city) & (plants["state_norm"] == state)]
        exact = candidates[candidates["name_norm"] == name]
        if not exact.empty:
            return str(exact.iloc[0]["plant_id"]), "exact_name_city_state", 1.0
        best_id = None
        best_score = 0.0
        for _, plant in candidates.iterrows():
            score = SequenceMatcher(None, name, str(plant["name_norm"])).ratio()
            if score > best_score:
                best_score = score
                best_id = str(plant["plant_id"])
        if best_id and best_score >= 0.78:
            return best_id, "fuzzy_name_city_state", round(best_score, 4)

    if city and state:
        candidates = plants[(plants["city_norm"] == city) & (plants["state_norm"] == state)]
        if len(candidates) == 1:
            return str(candidates.iloc[0]["plant_id"]), "city_state_single", 0.75

    return None, "unmatched", None


def normalize_rows(
    path: Path,
    sheet: SheetRead,
    plants: pd.DataFrame,
    existing_keys: set[tuple[str | None, str | None, str, str | None, str | None]],
) -> list[dict[str, Any]]:
    cols = canonical_columns(sheet.df)
    inferred_date = infer_date_from_filename(path)
    records = []
    for row_index, raw in sheet.df.iterrows():
        raw_dict = raw.to_dict()
        commodity = clean_text(raw_dict.get(cols.get("commodity"))) or "Corn"
        if commodity and commodity.lower() != "corn":
            continue
        column_date = parse_date_value(raw_dict.get(cols.get("date"))) if cols.get("date") else None
        date = column_date
        date_source = "column" if column_date else None
        date_file_mismatch = bool(inferred_date and column_date and inferred_date != column_date)
        if date_file_mismatch:
            date = inferred_date
            date_source = "filename_overrode_column_mismatch"
        elif not date:
            date = inferred_date
            date_source = "filename" if date else None

        normalized = {
            "source_file": str(path),
            "source_file_name": path.name,
            "source_sheet": sheet.sheet_name,
            "source_row": int(row_index) + 2,
            "date": date,
            "date_column_original": column_date,
            "date_from_filename": inferred_date,
            "date_source": date_source,
            "date_file_mismatch": date_file_mismatch,
            "plant_id_original": clean_text(raw_dict.get(cols.get("plant_id"))) if cols.get("plant_id") else None,
            "plant_id": clean_text(raw_dict.get(cols.get("plant_id"))) if cols.get("plant_id") else None,
            "ownership": clean_text(raw_dict.get(cols.get("ownership"))) if cols.get("ownership") else None,
            "plant_name": clean_text(raw_dict.get(cols.get("plant_name"))) if cols.get("plant_name") else None,
            "city": clean_text(raw_dict.get(cols.get("city"))) if cols.get("city") else None,
            "state": normalize_state(raw_dict.get(cols.get("state"))) if cols.get("state") else None,
            "latitude": parse_number(raw_dict.get(cols.get("latitude"))) if cols.get("latitude") else None,
            "longitude": parse_number(raw_dict.get(cols.get("longitude"))) if cols.get("longitude") else None,
            "basis": parse_number(raw_dict.get(cols.get("basis"))) if cols.get("basis") else None,
            "basis_source_column": cols.get("basis"),
            "flat_price": parse_number(raw_dict.get(cols.get("flat_price"))) if cols.get("flat_price") else None,
            "contract": clean_text(raw_dict.get(cols.get("contract"))) if cols.get("contract") else None,
            "delivery_month": normalize_delivery_month(raw_dict.get(cols.get("delivery_month"))) if cols.get("delivery_month") else None,
            "commodity": "Corn",
            "capacity_mgy": parse_number(raw_dict.get(cols.get("capacity_mgy"))) if cols.get("capacity_mgy") else None,
            "technology": clean_text(raw_dict.get(cols.get("technology"))) if cols.get("technology") else None,
            "rail_lines": clean_text(raw_dict.get(cols.get("rail_lines"))) if cols.get("rail_lines") else None,
            "corn_ci": parse_number(raw_dict.get(cols.get("corn_ci"))) if cols.get("corn_ci") else None,
            "fiber_ci": parse_number(raw_dict.get(cols.get("fiber_ci"))) if cols.get("fiber_ci") else None,
        }
        if not any(normalized.get(key) for key in ["plant_id", "plant_name", "city", "basis", "flat_price"]):
            continue
        matched_id, confidence, score = match_plant(normalized, plants)
        normalized["matched_plant_id"] = matched_id
        normalized["match_confidence"] = confidence
        normalized["match_score"] = score
        normalized["production_duplicate_candidate"] = (
            (
                normalized["date"],
                matched_id,
                normalized["commodity"],
                normalized["delivery_month"],
                normalized["contract"],
            )
            in existing_keys
        )
        records.append(normalized)
    return records


def inventory_file(path: Path, sheets: list[SheetRead]) -> dict[str, Any]:
    sheet_names = [sheet.sheet_name for sheet in sheets if sheet.sheet_name]
    row_count = sum(len(sheet.df) for sheet in sheets if sheet.error is None)
    columns = sorted({str(col) for sheet in sheets for col in sheet.df.columns})
    cols = {field for sheet in sheets for field in canonical_columns(sheet.df)}
    inferred = []
    if "date" not in cols and infer_date_from_filename(path):
        inferred.append("date_from_filename")
    if "commodity" not in cols:
        inferred.append("commodity_corn_default")
    missing_core = [field for field in CORE_FIELDS if field not in cols and not (field == "date" and "date_from_filename" in inferred) and not (field == "commodity" and "commodity_corn_default" in inferred)]
    appears_basis = "basis" in cols and bool({"plant_id", "plant_name", "city", "state"} & cols)
    reject_reason = None
    if any(sheet.error for sheet in sheets):
        reject_reason = "; ".join(filter(None, [sheet.error for sheet in sheets]))
    elif not appears_basis:
        reject_reason = "missing basis or plant/location identifiers"
    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_type": path.suffix.lower(),
        "modified_date": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "file_size_bytes": path.stat().st_size,
        "sheet_names": "|".join(sheet_names),
        "row_count": row_count,
        "column_names": "|".join(columns),
        "appears_basis_data": appears_basis,
        "usable_for_staging": appears_basis and reject_reason is None,
        "present_core_fields": "|".join([field for field in CORE_FIELDS if field in cols]),
        "missing_core_fields": "|".join(missing_core),
        "inferred_fields": "|".join(inferred),
        "optional_fields_present": "|".join([field for field in OPTIONAL_FIELDS if field in cols]),
        "reject_reason": reject_reason,
    }


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    lines = [
        "# Corn Basis Backfill Audit",
        "",
        "This audit did not write to the production SQLite database.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
    lines.extend(
        [
            "",
            "## Review Files",
            "",
            "- `file_inventory.csv`",
            "- `normalized_preview.csv`",
            "- `unmatched_rows.csv`",
            "- `duplicate_candidates.csv`",
            "- `data_quality_summary.csv`",
            "- `basis_backfill_staging.sqlite`",
            "",
            "## Recommendation",
            "",
            "Review unmatched rows and duplicate candidates before building any production import.",
            "A future production import script should require an explicit `--confirm-production-import` flag.",
        ]
    )
    (output_dir / "backfill_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    old_dir = Path(args.old_dir)
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in old_dir.rglob("*") if path.is_file() and path.suffix.lower() in FILE_EXTENSIONS)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        plants = load_plant_master(conn)
        existing_keys = load_existing_keys(conn)

    inventory = []
    normalized_rows: list[dict[str, Any]] = []
    for index, file_path in enumerate(files, start=1):
        if index == 1 or index % 25 == 0 or index == len(files):
            print(f"Scanning {index}/{len(files)}: {file_path.name}", flush=True)
        sheets = read_old_file(file_path, args.sample_rows)
        inv = inventory_file(file_path, sheets)
        inventory.append(inv)
        if inv["usable_for_staging"]:
            for sheet in sheets:
                if sheet.error is None and not sheet.df.empty:
                    normalized_rows.extend(normalize_rows(file_path, sheet, plants, existing_keys))

    inventory_df = pd.DataFrame(inventory)
    normalized_df = pd.DataFrame(normalized_rows)
    if normalized_df.empty:
        normalized_df = pd.DataFrame(columns=[
            "source_file", "source_sheet", "source_row", *CORE_FIELDS, *OPTIONAL_FIELDS,
            "matched_plant_id", "match_confidence", "match_score", "production_duplicate_candidate",
        ])

    duplicate_cols = ["date", "matched_plant_id", "commodity", "delivery_month", "contract"]
    normalized_df["staging_duplicate_candidate"] = normalized_df.duplicated(duplicate_cols, keep=False) if len(normalized_df) else []
    duplicate_df = normalized_df[
        normalized_df.get("production_duplicate_candidate", False).fillna(False)
        | normalized_df.get("staging_duplicate_candidate", False).fillna(False)
    ].copy()
    unmatched_df = normalized_df[normalized_df["match_confidence"] == "unmatched"].copy() if "match_confidence" in normalized_df else normalized_df.copy()

    summary = {
        "total_files_scanned": len(inventory_df),
        "usable_files": int(inventory_df["usable_for_staging"].sum()) if not inventory_df.empty else 0,
        "rejected_files": int((~inventory_df["usable_for_staging"]).sum()) if not inventory_df.empty else 0,
        "total_rows_found": int(inventory_df["row_count"].sum()) if not inventory_df.empty else 0,
        "rows_successfully_normalized": len(normalized_df),
        "rows_matched_to_plant_master": int((normalized_df["match_confidence"] != "unmatched").sum()) if not normalized_df.empty else 0,
        "rows_missing_basis": int(normalized_df["basis"].isna().sum()) if not normalized_df.empty else 0,
        "rows_missing_date": int(normalized_df["date"].isna().sum()) if not normalized_df.empty else 0,
        "rows_missing_delivery_month": int(normalized_df["delivery_month"].isna().sum()) if not normalized_df.empty else 0,
        "rows_missing_plant_match": len(unmatched_df),
        "duplicate_candidate_rows": len(duplicate_df),
        "date_min": normalized_df["date"].dropna().min() if not normalized_df.empty and normalized_df["date"].notna().any() else None,
        "date_max": normalized_df["date"].dropna().max() if not normalized_df.empty and normalized_df["date"].notna().any() else None,
    }

    inventory_df.to_csv(output_dir / "file_inventory.csv", index=False)
    normalized_df.to_csv(output_dir / "normalized_preview.csv", index=False)
    unmatched_df.to_csv(output_dir / "unmatched_rows.csv", index=False)
    duplicate_df.to_csv(output_dir / "duplicate_candidates.csv", index=False)
    pd.DataFrame([summary]).to_csv(output_dir / "data_quality_summary.csv", index=False)
    with sqlite3.connect(output_dir / "basis_backfill_staging.sqlite") as staging:
        normalized_df.to_sql("corn_basis_staging_old_files", staging, if_exists="replace", index=False)
        inventory_df.to_sql("file_inventory", staging, if_exists="replace", index=False)
    write_report(summary, output_dir)

    print(json.dumps(summary, indent=2, default=str))
    print(f"Audit outputs written to {output_dir}")


if __name__ == "__main__":
    main()
