#!/usr/bin/env python
# coding: utf-8

# 0) Imports and setup
from __future__ import annotations
import tarfile
from pathlib import Path
from reed import utils
from collections import defaultdict, Counter
from functools import reduce
import re
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd


# 1) Sensordata import functions

def parse_event_and_type_from_csv_filename(csv_filename: str) -> tuple[str, str | None]:
    """
    Parse event_id and measurement_type from CSV filename.

    Expected filename pattern (without extension), e.g.:
        OF10001_G_TXG_REGRHM_92SQBY

    Rules:
      - measurement_type = last 6 characters
      - event_id = remaining prefix (without trailing underscore)

    Returns
    -------
    (event_id, measurement_type)
    """
    base = Path(csv_filename).name
    stem = base[:-4] if base.lower().endswith(".csv") else base

    if len(stem) < 6:
        return stem, None

    measurement_type = stem[-6:]
    event_part = stem[:-6]
    event_id = event_part[:-1] if event_part.endswith("_") else event_part
    return event_id, measurement_type


def load_monitoring_records(
    monitoring_data_path: Path,
    *,
    debug: bool = False
) -> list[dict]:
    """
    Load all sensor CSV files stored inside .tar/.tar.gz archives
    under the monitoring data directory.

    Each returned record contains:
      - company
      - machine_name
      - event_id
      - measurement_type
      - tar_path
      - csv_name (path inside archive)
      - csv_basename
      - data (DataFrame)

    Parameters
    ----------
    monitoring_data_path : Path
        Root folder containing company subfolders with tar archives.

    debug : bool
        If True, prints warnings and duplicate information.

    Returns
    -------
    list[dict]
    """
    all_records: list[dict] = []

    for company_folder in monitoring_data_path.iterdir():
        if not company_folder.is_dir():
            continue

        # Company name = first part before " - "
        parts = [p.strip() for p in company_folder.name.split(" - ")]
        if not parts or not parts[0]:
            if debug:
                print("Warning — unexpected folder name:", company_folder.name)
            continue

        company = parts[0].lower()
        machine_name = " - ".join(parts[1:]) if len(parts) > 1 else None

        tar_files = list(company_folder.rglob("*.tar")) + list(company_folder.rglob("*.tar.gz"))

        if not tar_files:
            if debug:
                print(f"No .tar/.tar.gz files found in {company_folder.name}")
            continue

        seen_csv_basenames: list[str] = []

        for tar_path in tar_files:
            try:
                with tarfile.open(tar_path, mode="r:*") as tf:
                    csv_members = [
                        m for m in tf.getmembers()
                        if m.name.lower().endswith(".csv")
                    ]

                    if not csv_members:
                        if debug:
                            print(f"No CSV files found in archive {tar_path.name}")
                        continue

                    for csv_member in csv_members:
                        csv_basename = Path(csv_member.name).name
                        seen_csv_basenames.append(csv_basename)

                        event_id, measurement_type = (
                            parse_event_and_type_from_csv_filename(csv_basename)
                        )

                        f = tf.extractfile(csv_member)
                        if f is None:
                            if debug:
                                print(
                                    f"Warning — could not extract {csv_member.name} "
                                    f"from {tar_path}"
                                )
                            continue

                        df = pd.read_csv(f)

                        all_records.append({
                            "company": company,
                            "machine_name": machine_name,
                            "event_id": event_id,
                            "measurement_type": measurement_type,
                            "tar_path": tar_path,
                            "csv_name": csv_member.name,
                            "csv_basename": csv_basename,
                            "data": df,
                        })

            except tarfile.TarError as e:
                if debug:
                    print(f"Warning — could not open archive {tar_path} | {e}")

        # Duplicate basename warning within company folder
        if debug:
            counts = Counter(seen_csv_basenames)
            duplicates = [name for name, cnt in counts.items() if cnt > 1]
            if duplicates:
                print(f"\n⚠ Duplicate CSV basenames in '{company_folder.name}':")
                for name in sorted(duplicates):
                    print(f"  - {name} (x{counts[name]})")

    if debug:
        print("\nTotal CSV files imported:", len(all_records))

    return all_records


def group_records_by_event(
    records: list[dict]
) -> dict[tuple[str, str], list[dict]]:
    """
    Group records by (company, event_id).
    """
    events: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for rec in records:
        events[(rec["company"], rec["event_id"])].append(rec)
    return events


# Import of tool keys functions

def load_tool_operation_keys(
    tool_descriptions_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load tool-operation mapping tables from the Excel workbook
    `tool_operation_combined.xlsx`.

    The workbook contains:
      - Company-specific sheets (KOMATSU, WWR, GOIMEK)
      - A REED sheet with operation → REED tool mappings

    This function returns:

    key_company_tools : DataFrame
        Combined table from company sheets with columns:
            - company
            - Tool_Number (numeric)
            - OP TYPE

        Tool_Number values are:
            - whitespace removed
            - split on "/" if multiple tools listed
            - exploded to one row per tool
            - converted to numeric where possible

        Company names are lowercased.

    key_reed_tools : DataFrame
        REED mapping sheet with original column names preserved.

    Parameters
    ----------
    tool_descriptions_path : Path
        Folder containing tool_operation_combined.xlsx

    Returns
    -------
    (key_company_tools, key_reed_tools)
    """
    xlsx_path = tool_descriptions_path / "tool_operation_combined.xlsx"

    company_sheets = ["KOMATSU", "WWR", "GOIMEK"]
    company_frames: list[pd.DataFrame] = []

    for sheet in company_sheets:
        df = pd.read_excel(xlsx_path, sheet_name=sheet, skiprows=1)

        df_out = df[["TOOL", "OP TYPE"]].copy()
        df_out.insert(0, "company", sheet.lower())
        df_out = df_out.rename(columns={"TOOL": "Tool_Number"})

        # Normalize and split tool numbers like "123 / 124"
        df_out["Tool_Number"] = (
            df_out["Tool_Number"]
            .astype(str)
            .str.replace(" ", "", regex=False)
            .str.split("/")
        )

        df_out["OP TYPE"] = df_out["OP TYPE"].astype(str).str.strip()

        df_out = df_out.explode("Tool_Number", ignore_index=True)
        df_out["Tool_Number"] = pd.to_numeric(df_out["Tool_Number"], errors="coerce")

        company_frames.append(df_out)

    key_company_tools_raw = pd.concat(company_frames, ignore_index=True)
    
    # Find ambugious keys: Same Tool_Number for same company maps to multiple OP TYPE values
    amb_keys = (
        key_company_tools_raw.groupby(["company", "Tool_Number"])["OP TYPE"]
        .nunique()
        .reset_index(name="n_op_types")
        .query("n_op_types > 1")
    )

    # Save ambiguous keys with their candidate OP TYPE values for reference
    ambiguous_company_tools = (
        key_company_tools_raw.merge(amb_keys[["company", "Tool_Number"]], on=["company", "Tool_Number"], how="inner")
        .groupby(["company", "Tool_Number"])["OP TYPE"]
        .apply(lambda s: sorted(set(s)))
        .reset_index(name="op_type_candidates")
        .sort_values(["company", "Tool_Number"])
        .reset_index(drop=True)
    )

    # Drop ambiguous keys from the main mapping to avoid duplicate merges later.
    if not amb_keys.empty:
        # anti-join
        key_company_tools = (
            key_company_tools_raw.merge(amb_keys[["company", "Tool_Number"]], on=["company", "Tool_Number"], how="left", indicator=True)
            .query("_merge == 'left_only'")
            .drop(columns=["_merge"])
        )
    else:
        key_company_tools = key_company_tools_raw.copy()

    # one row per (company, Tool_Number) with OP TYPE
    key_company_tools = (
        key_company_tools.sort_values(["company", "Tool_Number", "OP TYPE"])
        .drop_duplicates(["company", "Tool_Number"], keep="first")
        .reset_index(drop=True)
    )

    # --- Load REED mapping ---
    key_reed_tools_raw = pd.read_excel(xlsx_path, sheet_name="REED")

    # Same procedure for REED mapping: Check for ambiguous OP TYPE → reed tool mappings and save them separately.
    if {"OP TYPE", "reed tool"}.issubset(key_reed_tools_raw.columns):
        amb_ops = (
            key_reed_tools_raw.groupby("OP TYPE")["reed tool"]
            .nunique()
            .reset_index(name="n_reed_tools")
            .query("n_reed_tools > 1")
        )
        ambiguous_reed = (
            key_reed_tools_raw.merge(amb_ops[["OP TYPE"]], on="OP TYPE", how="inner")
            .groupby("OP TYPE")["reed tool"]
            .apply(lambda s: sorted(set(s)))
            .reset_index(name="reed_tool_candidates")
        )
        
        if not amb_ops.empty:
            key_reed_tools = (
                key_reed_tools_raw.merge(amb_ops[["OP TYPE"]], on="OP TYPE", how="left", indicator=True)
                .query("_merge == 'left_only'")
                .drop(columns=["_merge"])
            )
        else:
            key_reed_tools = key_reed_tools_raw.copy()

        key_reed_tools = key_reed_tools.drop_duplicates(["OP TYPE"], keep="first").reset_index(drop=True)

    else:
        key_reed_tools = key_reed_tools_raw

    return key_company_tools, key_reed_tools, ambiguous_company_tools

# Data analsysis functions

def merge_records(records):
    """
    Creating one dataFrame for each event.

    """
    dfs = []
    cols = ["timestamp", "Tool_Number", "Power_Active", "Energy_Total"]

    merged = None
    
    for i, r in enumerate(records):
        df = r["data"].copy()
        df = df[[c for c in cols if c in df.columns]].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.floor('s')
        df = df.set_index("timestamp")

        if merged is None:
            merged = df
        else:
            merged = merged.join(df, how="outer")

    merged = merged.sort_index()
            
    return merged

def build_final_df(
    events: Dict[Tuple[str, str], List[dict]],
    key_company_tools: pd.DataFrame,
    key_reed_tools: pd.DataFrame,
    *,
    debug: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build the final aggregated dataframe from raw event records and mapping keys.

    Steps:
      1) For each (company, event_id), merge sensor records into a single time-indexed df.
      2) Compute per-row energy consumption from Power_Active.
      3) Aggregate by Tool_Number within each event.
      4) Merge in OP TYPE mapping (company + Tool_Number).
      5) Merge in REED mapping (OP TYPE -> REED tool).
      6) Fill missing 'reed tool' with default.

    Parameters
    ----------
    events:
        Dict mapping (company, event_id) -> list of record dicts (each contains "data" DataFrame).
    key_company_tools:
        DataFrame with columns: company, Tool_Number, OP TYPE
    key_reed_tools:
        DataFrame keyed by "OP TYPE" and containing "reed tool" (and potentially other columns).
    debug:
        If True, prints diagnostics and drops into breakpoint() on missing Power_Active.
        If False, raises ValueError on missing Power_Active.

    Returns
    -------
    final_df:
        Indexed by (company, event_id, Tool_Number) with aggregated fields + mappings.
    event_summaries_df:
        DataFrame with columns: company, event_id, energy_meter_total
    """
    all_grouped: list[pd.DataFrame] = []
    event_summaries: list[dict] = []

    for (company, event_id), records in events.items():
        merged_df = merge_records(records)

        if merged_df.empty or "Power_Active" not in merged_df.columns:
            msg = (
                f"MISSING Power_Active | company={company} | event_id={event_id} | "
                f"shape={merged_df.shape} | columns={list(merged_df.columns)}"
            )

            if debug:
                print("\n---", msg, "---")
                print("records type:", type(records), "len:", len(records))
                if len(records) > 0:
                    r0 = records[0]
                    if isinstance(r0, dict):
                        print("first record keys:", list(r0.keys()))
                breakpoint()
            else:
                raise ValueError(msg)

        # Energy consumption from active power (assumes Power_Active in W and 1-second sampling)
        merged_df["energy_consumption"] = merged_df["Power_Active"] / 3600.0

        merged_df = merged_df.reset_index()

        # Meter-based energy delta (if Energy_Total exists)
        s = merged_df["Energy_Total"].dropna() if "Energy_Total" in merged_df.columns else pd.Series(dtype=float)
        meter_energy = np.nan if s.empty else (s.iloc[-1] - s.iloc[0])

        event_summaries.append({
            "company": company,
            "event_id": event_id,
            "energy_meter_total": meter_energy,
        })

        # Aggregate within event by Tool_Number
        grouped_df = (
            merged_df
            .groupby("Tool_Number", as_index=False)
            .agg(
                energy_consumption=("energy_consumption", "sum"),
                Power_Active=("Power_Active", "mean"),
                seconds=("timestamp", "count"),
            )
        )

        grouped_df["hours"] = grouped_df["seconds"] / 3600.0
        grouped_df["company"] = company
        grouped_df["event_id"] = event_id

        grouped_df = grouped_df.set_index(["company", "event_id", "Tool_Number"])
        all_grouped.append(grouped_df)

    if not all_grouped:
        raise ValueError("No grouped data produced. Check input events/records.")

    final_df = pd.concat(all_grouped).reset_index()

    # Ensure Tool_Number is numeric for merges
    final_df["Tool_Number"] = pd.to_numeric(final_df["Tool_Number"], errors="coerce")

    # Merge 1: add OP TYPE based on company + Tool_Number
    final_df = final_df.merge(
        key_company_tools[["company", "Tool_Number", "OP TYPE"]],
        on=["company", "Tool_Number"],
        how="left",
        validate="many_to_one",
    )

    # Merge 2: add REED mapping based on OP TYPE
    final_df = final_df.merge(
        key_reed_tools,
        on="OP TYPE",
        how="left",
        validate="many_to_one",
        suffixes=("", "_reed"),
    )

    # Default REED tool when missing
    if "reed tool" in final_df.columns:
        final_df["reed tool"] = final_df["reed tool"].fillna("generic machining, soraluce")
    else:
        # If key_reed_tools uses a different column name, fail loudly
        raise KeyError("Expected column 'reed tool' not found after merging key_reed_tools.")

    final_df = final_df.set_index(["company", "event_id", "Tool_Number"])

    event_summaries_df = pd.DataFrame(event_summaries)

    return final_df, event_summaries_df

# Sensordata_analysis

def run_sensordata_analysis(
    monitoring_data_path: Path,
    tool_descriptions_path: Path,
    *,
    debug: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    End-to-end sensor data analysis pipeline up to and including build_final_df().

    Steps:
      1) Load monitoring records from .tar/.tar.gz archives
      2) Group records into events by (company, event_id)
      3) Load mapping keys from tool_operation_combined.xlsx
      4) Build final aggregated dataframe + event summaries

    Parameters
    ----------
    monitoring_data_path : Path
        Folder containing company subfolders with monitoring archives.
    tool_descriptions_path : Path
        Folder containing tool_operation_combined.xlsx.
    debug : bool
        Enables verbose diagnostics and breakpoints in downstream functions.

    Returns
    -------
    final_df : pd.DataFrame
        Indexed by (company, event_id, Tool_Number), with OP TYPE and REED tool mapping.
    event_summaries_df : pd.DataFrame
        Columns: company, event_id, energy_meter_total
    """
    # 1) Load raw CSVs from archives
    records = load_monitoring_records(monitoring_data_path, debug=debug)

    # 2) Group into events
    events = group_records_by_event(records)

    # 3) Load mapping keys
    key_company_tools, key_reed_tools, ambiguous_company_tools = load_tool_operation_keys(tool_descriptions_path)

    # 4) Build final dataframe
    final_df, event_summaries_df = build_final_df(
        events=events,
        key_company_tools=key_company_tools,
        key_reed_tools=key_reed_tools,
        debug=debug,
    )

    return final_df, event_summaries_df, ambiguous_company_tools, key_company_tools, key_reed_tools

#Other analysis functions
def find_missing_op_type_tools(final_df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify tool numbers that are missing an OP TYPE mapping.

    Parameters
    ----------
    final_df : DataFrame
        Final aggregated dataframe indexed by
        (company, event_id, Tool_Number) and containing column "OP TYPE".

    Returns
    -------
    DataFrame
        Table with unique (company, Tool_Number) pairs where OP TYPE is missing,
        sorted by company and Tool_Number.
    """
    if "OP TYPE" not in final_df.columns:
        raise KeyError("Column 'OP TYPE' not found in final_df")

    missing = (
        final_df
        .loc[final_df["OP TYPE"].isna()]
        .reset_index()[["company", "Tool_Number"]]
        .drop_duplicates()
        .sort_values(["company", "Tool_Number"])
        .reset_index(drop=True)
    )

    return missing

def split_final_df_by_company_event(final_df):
    dfs = {}

    for (company, event_id), df in final_df.groupby(level=["company", "event_id"]):
        dfs[(company, event_id)] = df.reset_index()

    return dfs


def sum_by_reed_tool(
    df,
    group_cols=("company", "event_id", "reed tool"),
    cols_to_sum=("energy_consumption", "hours")
):
    result = (
        df
        .drop(columns=["Tool_Number", "seconds"], errors="ignore")
        .groupby(list(group_cols), as_index=False)
        .agg({col: "sum" for col in cols_to_sum})
    )

    result["Power_Active"] = result["energy_consumption"] / result["hours"]
    result = result.set_index(["company", "event_id", "reed tool"]).sort_index()

    return result

def compute_event_totals(
    final_df: pd.DataFrame,
    event_summaries: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute per-event totals and compare calculated energy with meter totals.

    Aggregates final_df by (company, event_id) and joins meter-based
    energy totals from event_summaries. Also computes relative difference
    between calculated and meter energy.

    Parameters
    ----------
    final_df : DataFrame
        Final aggregated dataframe indexed by
        (company, event_id, Tool_Number) and containing at least:
            - energy_consumption
            - Power_Active
            - hours

    event_summaries : DataFrame
        DataFrame with columns:
            - company
            - event_id
            - energy_meter_total

    Returns
    -------
    DataFrame
        Indexed by (company, event_id) with columns:
            - energy_consumption (sum)
            - Power_Active (mean)
            - hours (sum)
            - energy_meter_total
            - rel_diff_calc_vs_meter
    """
    required_cols = {"energy_consumption", "Power_Active", "hours"}
    missing_cols = required_cols - set(final_df.columns)
    if missing_cols:
        raise KeyError(f"final_df missing required columns: {missing_cols}")

    df_totals = (
        final_df
        .reset_index()
        .groupby(["company", "event_id"], as_index=False)
        .agg({
            "energy_consumption": "sum",
            "Power_Active": "mean",
            "hours": "sum",
        })
        .set_index(["company", "event_id"])
    )

    # Ensure proper index on event_summaries
    if not {"company", "event_id", "energy_meter_total"}.issubset(event_summaries.columns):
        raise KeyError("event_summaries must contain company, event_id, energy_meter_total")

    df_meter = event_summaries.set_index(["company", "event_id"])

    df_totals = df_totals.join(df_meter)

    df_totals["rel_diff_calc_vs_meter"] = (
        (df_totals["energy_consumption"] - df_totals["energy_meter_total"])
        / df_totals["energy_meter_total"]
    )

    return df_totals

