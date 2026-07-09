#!/usr/bin/env python
"""
Export dashboard-ready corn basis JSON files.

Run this after the Monday scraper has written the latest rows to the master
SQLite database. The browser should read these JSON outputs from GitHub Pages,
Cloudflare R2, or another static file host; it should not query SQLite.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_DB_PATH = (
    r"C:\Users\ehakm\OneDrive\Documents\Python Code\Ethanol db"
    r"\Ethanol DB\ethanol_production.db"
)
DEFAULT_OUTPUT_DIR = Path("r2_upload/corn_basis")

SNAPSHOT_FIELDS = [
    "date",
    "plant_id",
    "plant_name",
    "ownership",
    "city",
    "state",
    "latitude",
    "longitude",
    "basis",
    "flat_price",
    "contract",
    "delivery_month",
    "capacity_mgy",
    "technology",
    "rail_lines",
    "corn_ci",
    "fiber_ci",
    "source_file",
]


ALIASES = {
    "plant_id": ["Epm_number", "EPM", "epm", "plant_id"],
    "plant_name": ["Name", "Plant Name", "Plant", "plant_name"],
    "ownership": ["Ownership", "Ownership Group", "Owner", "ownership"],
    "city": ["City", "city"],
    "state": ["State", "state"],
    "latitude": ["Latitude", "Lat", "latitude", "lat"],
    "longitude": ["Longitude", "Lon", "Lng", "longitude", "lon", "lng"],
    "basis": ["Adj_Basis", "Basis_price", "Basis", "basis"],
    "flat_price": ["Flat", "Flat_Price", "flat_price"],
    "contract": ["Contract_Month", "Contract", "contract"],
    "delivery_month": ["Del_Month", "Delivery_Month", "delivery_month"],
    "capacity_mgy": ["Ethanol Capacity", "Capacity", "capacity_mgy"],
    "technology": ["Technology", "Plant Design", "technology"],
    "rail_lines": ["Rail Lines", "Rail", "rail_lines"],
    "corn_ci": ["Corn CI", "Corn_CI", "corn_ci"],
    "fiber_ci": ["Fiber CI", "Fiber_CI", "fiber_ci"],
    "source_file": ["Source_File", "Source File", "source_file"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export static JSON files for the corn basis dashboard."
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output folder for R2-ready corn_basis JSON files.",
    )
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=None,
        help="Optional limit on exported snapshot dates, newest first.",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional inclusive start date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--mondays-only",
        action="store_true",
        help="Export only Monday snapshot dates after parsing database dates.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON for review. Defaults to compact JSON.",
    )
    return parser.parse_args()


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    try:
        return pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
    except Exception as exc:  # pragma: no cover - exercised against local DB
        raise RuntimeError(f"Could not read required table {table!r}: {exc}") from exc


def first_present(df: pd.DataFrame, aliases: Iterable[str]) -> str | None:
    lower_to_actual = {str(col).lower(): str(col) for col in df.columns}
    for alias in aliases:
        actual = lower_to_actual.get(alias.lower())
        if actual is not None:
            return actual
    return None


def pick(df: pd.DataFrame, field: str) -> pd.Series:
    col = first_present(df, ALIASES[field])
    if col is None:
        return pd.Series([pd.NA] * len(df), index=df.index)
    return df[col]


def parse_dates(values: pd.Series) -> pd.Series:
    raw = values.astype("string").str.strip()
    parsed = pd.to_datetime(raw, errors="coerce")
    missing = parsed.isna()
    for fmt in ("%m%d%y", "%m/%d/%y", "%Y%m%d", "%Y-%m-%d"):
        if not missing.any():
            break
        parsed_fmt = pd.to_datetime(raw[missing], format=fmt, errors="coerce")
        parsed.loc[missing] = parsed_fmt
        missing = parsed.isna()
    return parsed


def to_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return None
    return float(num)


def clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_rail_lines(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    for sep in [";", "|", "/"]:
        text = text.replace(sep, ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def records_for_json(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in df[SNAPSHOT_FIELDS].to_dict("records"):
        cleaned: dict[str, Any] = {}
        for key, value in row.items():
            if key in {
                "latitude",
                "longitude",
                "basis",
                "flat_price",
                "capacity_mgy",
                "corn_ci",
                "fiber_ci",
            }:
                cleaned[key] = to_number(value)
            elif key == "rail_lines":
                cleaned[key] = normalize_rail_lines(value)
            else:
                cleaned[key] = clean_text(value)
        records.append(cleaned)
    return records


def plant_history_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        records.append(
            {
                "date": clean_text(row.get("date")),
                "plant_id": clean_text(row.get("plant_id")),
                "plant_name": clean_text(row.get("plant_name")),
                "ownership": clean_text(row.get("ownership")),
                "city": clean_text(row.get("city")),
                "state": clean_text(row.get("state")),
                "latitude": to_number(row.get("latitude")),
                "longitude": to_number(row.get("longitude")),
                "basis": to_number(row.get("basis")),
                "flat_price": to_number(row.get("flat_price")),
                "contract": clean_text(row.get("contract")),
                "delivery_month": clean_text(row.get("delivery_month")),
                "capacity_mgy": to_number(row.get("capacity_mgy")),
                "technology": clean_text(row.get("technology")),
                "rail_lines": normalize_rail_lines(row.get("rail_lines")),
                "corn_ci": to_number(row.get("corn_ci")),
                "fiber_ci": to_number(row.get("fiber_ci")),
                "source_file": clean_text(row.get("source_file")),
            }
        )
    return records


def build_dashboard_frame(corn_basis: pd.DataFrame, plants: pd.DataFrame) -> pd.DataFrame:
    date_col = first_present(corn_basis, ["Date", "Basis_Date", "date"])
    if date_col is None:
        raise RuntimeError("CornBasis must contain a Date or Basis_Date column.")

    corn = corn_basis.copy()
    corn["_basis_timestamp"] = parse_dates(corn[date_col])
    corn = corn.dropna(subset=["_basis_timestamp"]).copy()
    corn["date"] = corn["_basis_timestamp"].dt.strftime("%Y-%m-%d")

    basis_id = first_present(corn, ALIASES["plant_id"])
    plant_id = first_present(plants, ALIASES["plant_id"])
    if basis_id is None:
        raise RuntimeError("CornBasis must contain Epm_number, EPM, or plant_id.")

    if plant_id is not None:
        corn["_plant_id_key"] = corn[basis_id].astype("string").str.strip()
        plant_meta = plants.copy()
        plant_meta["_plant_id_key"] = plant_meta[plant_id].astype("string").str.strip()
        plant_meta = plant_meta.drop_duplicates("_plant_id_key", keep="last")
        merged = corn.merge(
            plant_meta,
            on="_plant_id_key",
            how="left",
            suffixes=("", "_plant"),
        )
    else:
        merged = corn

    out = pd.DataFrame(index=merged.index)
    out["date"] = merged["date"]
    for field in SNAPSHOT_FIELDS:
        if field == "date":
            continue
        out[field] = pick(merged, field)

    out["plant_id"] = out["plant_id"].astype("string").str.strip()
    out = out[out["plant_id"].notna() & (out["plant_id"] != "")].copy()

    sort_cols = ["date", "plant_id", "_basis_timestamp"]
    for optional in ["contract", "delivery_month"]:
        if optional in out.columns:
            sort_cols.append(optional)
    out["_basis_timestamp"] = merged.loc[out.index, "_basis_timestamp"]
    out = out.sort_values(sort_cols)
    out = out.drop_duplicates(["date", "plant_id"], keep="last")

    for field in ["latitude", "longitude", "basis", "flat_price", "capacity_mgy", "corn_ci", "fiber_ci"]:
        out[field] = pd.to_numeric(out[field], errors="coerce")

    return out[SNAPSHOT_FIELDS].sort_values(["date", "state", "plant_name", "plant_id"])


def numeric_summary(df: pd.DataFrame, group_cols: list[str]) -> list[dict[str, Any]]:
    tmp = df.copy()
    tmp["basis"] = pd.to_numeric(tmp["basis"], errors="coerce")
    tmp = tmp.dropna(subset=["basis"])
    if tmp.empty:
        return []
    grouped = (
        tmp.groupby(group_cols, dropna=False)
        .agg(
            avg_basis=("basis", "mean"),
            min_basis=("basis", "min"),
            max_basis=("basis", "max"),
            plant_count=("plant_id", "nunique"),
        )
        .reset_index()
    )
    for col in ["avg_basis", "min_basis", "max_basis"]:
        grouped[col] = grouped[col].round(4)
    return grouped.where(pd.notna(grouped), None).to_dict("records")


def write_json(path: Path, payload: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    path.write_text(json.dumps(payload, indent=indent, allow_nan=False) + "\n", encoding="utf-8")


def export_files(df: pd.DataFrame, output_dir: Path, pretty: bool, max_snapshots: int | None) -> tuple[int, str]:
    snapshots_dir = output_dir / "snapshots"
    history_dir = output_dir / "history"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    dates = sorted(df["date"].dropna().unique(), reverse=True)
    if max_snapshots is not None:
        dates = dates[:max_snapshots]
        df = df[df["date"].isin(dates)].copy()

    if not dates:
        raise RuntimeError("No valid snapshot dates were available to export.")

    newest = dates[0]
    for snapshot_date in dates:
        rows = records_for_json(df[df["date"] == snapshot_date])
        write_json(snapshots_dir / f"{snapshot_date}.json", rows, pretty)

    shutil.copyfile(snapshots_dir / f"{newest}.json", output_dir / "latest.json")
    write_json(output_dir / "index.json", {"latest": newest, "snapshots": dates}, pretty)

    write_json(history_dir / "all_basis_history.json", plant_history_records(df), pretty)
    return len(dates), newest


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    output_dir = Path(args.output_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        corn_basis = read_table(conn, "CornBasis")
        plants = read_table(conn, "Corn_Processors")

    df = build_dashboard_frame(corn_basis, plants)
    if args.start_date:
        start_date = pd.to_datetime(args.start_date).strftime("%Y-%m-%d")
        df = df[df["date"] >= start_date].copy()
    if args.mondays_only:
        weekdays = pd.to_datetime(df["date"], errors="coerce").dt.weekday
        df = df[weekdays == 0].copy()

    exported_count, newest = export_files(df, output_dir, args.pretty, args.max_snapshots)
    print(f"Exported {exported_count} snapshot date(s) to {output_dir} (latest: {newest})")


if __name__ == "__main__":
    main()
