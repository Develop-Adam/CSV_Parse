#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import sys
from pathlib import Path
import pandas as pd

#========================================================+=========================================#
'''
Constants
'''
NBSP = "\u00A0" # removes non-breaking spaces


#========================================================+=========================================#
'''
    check if NaN -> convert to string -> replace NBSP characters ->
    remove surrounding whitespace -> return cleaned string
'''
def clean_str(x):
    if pd.isna(x): 
        return ""
    return str(x).replace(NBSP, " ").strip()


#========================================================+=========================================#
'''
'''
def load_settings(path: Path) -> dict:
    """
    Load settings JSON. If missing, return {}.
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


#========================================================+=========================================#
'''
'''
def get_csv_read_kwargs(settings: dict) -> dict:
    csvs = (settings or {}).get("csv", {})
    kwargs: dict = {}

    # delimiter / encoding optional
    if csvs.get("delimiter"):
        kwargs["sep"] = csvs["delimiter"]
    if csvs.get("encoding"):
        kwargs["encoding"] = csvs["encoding"]

    # skip rows optional
    if "skip_rows" in csvs and csvs["skip_rows"] is not None:
        kwargs["skiprows"] = csvs["skip_rows"]

    # Force header from settings (ignore CSV header)
    if csvs.get("header_from_settings"):
        header = csvs.get("header")
        if not isinstance(header, list) or not header:
            raise ValueError("csv.header_from_settings is true, but csv.header is missing/empty.")
        kwargs["header"] = None          # DO NOT use any row as header
        kwargs["names"] = header         # Use settings header
    else:
        # Old behavior: header row from CSV (optional)
        if "header_row" in csvs and csvs["header_row"] is not None:
            kwargs["header"] = int(csvs["header_row"])

    return kwargs


#========================================================+=========================================#
'''
'''
def build_parser():
    p = argparse.ArgumentParser(description="Filter Work Orders CSV and export to JSON.")

    # Defaults so running with no args still produces an output
    p.add_argument("--input", default="inputs/WorkOrders.csv", help="Input CSV (default: inputs/WorkOrders.csv)")
    p.add_argument("--output", default="inputs/filtered.json", help="Output JSON (default: inputs/filtered.json)")

    # New: settings file
    p.add_argument(
        "--settings",
        default="inputs/settings.json",
        help="Settings JSON (default: inputs/settings.json). "
             "Used to set header row/skip rows/delimiter/encoding.",
    )

    # Filters
    p.add_argument("--status", help="Keep rows where Status == this (case-insensitive)")
    p.add_argument("--not-status", help="Exclude rows where Status == this (case-insensitive)")
    p.add_argument(
        "--contains",
        action="append",
        default=[],
        help="Filter where Column contains substring (case-insensitive). "
             "Repeatable. Format: 'Column::substring'",
    )

    # Optional date window (skipped if the column doesn't exist)
    p.add_argument(
        "--date-col",
        default=None,
        help="Column to date-filter on (optional; if omitted or missing, no date filter)",
    )
    p.add_argument("--date-from", help="Inclusive start date (YYYY-MM-DD)")
    p.add_argument("--date-to", help="Inclusive end date (YYYY-MM-DD)")

    # Output shaping
    p.add_argument("--keep-cols", help="Comma-separated list of columns to keep (after Q/A handling)")
    p.add_argument("--limit", type=int, help="Limit output rows (for testing)")
    p.add_argument(
        "--nest-qa",
        action="store_true",
        help="Nest Question/Answer pairs into a single 'qa' array of {question, answer} objects",
    )

    return p


#========================================================+=========================================#
'''
'''
def apply_contains(df, rules):
    for rule in rules:
        if "::" not in rule:
            raise ValueError(f"Invalid --contains rule '{rule}'. Use Column::substring")
        col, sub = rule.split("::", 1)
        col = col.strip()
        sub = clean_str(sub).lower()
        if col not in df.columns:
            raise ValueError(f"--contains refers to missing column '{col}'")
        df = df[
            df[col]
            .astype(str)
            .str.replace(NBSP, " ", regex=False)
            .str.strip()
            .str.lower()
            .str.contains(sub, na=False)
        ]
    return df


#========================================================+=========================================#
'''
'''
def select_cols(df, keep_cols):
    if not keep_cols:
        return df
    cols = [c.strip() for c in keep_cols.split(",") if c.strip()]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"--keep-cols columns not found: {missing}")
    return df[cols]


#========================================================+=========================================#
'''
'''
def build_qa_nested(row):
    qa_entries = []
    for c in row.index:
        if c.lower().startswith("question "):
            num = c.split(" ", 1)[1].strip()
            q = clean_str(row[c])
            a_col = f"Answer {num}"
            a = clean_str(row.get(a_col, ""))
            if q or a:
                qa_entries.append({"number": num, "question": q, "answer": a})
    return qa_entries


#========================================================+=========================================#
'''
'''
def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve to absolute paths (relative to script directory)
    script_dir = Path(__file__).resolve().parent

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (script_dir / input_path).resolve()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (script_dir / output_path).resolve()

    settings_path = Path(args.settings)
    if not settings_path.is_absolute():
        settings_path = (script_dir / settings_path).resolve()

    print(f"[INFO] Reading CSV: {input_path}")
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        return 2

    # Load settings (optional)
    settings = load_settings(settings_path)
    csv_kwargs = get_csv_read_kwargs(settings)
    if settings:
        print(f"[INFO] Using settings: {settings_path}")
        if csv_kwargs:
            print(f"[INFO] CSV read options: {csv_kwargs}")

    # Load as text; your file is comma-delimited with quoted fields by default
    df = pd.read_csv(
        input_path,
        dtype=str,
        keep_default_na=False,
        **csv_kwargs,
    )
    # print(f"[INFO] Loaded columns: {list(df.columns)}")

    # Clean whitespace/NBSP across all columns
    for c in df.columns:
        df[c] = df[c].apply(clean_str)

    in_rows = len(df)

    # Status filters
    if args.status:
        df = df[df.get("Status", "").str.lower() == args.status.strip().lower()]
    if args.not_status:
        df = df[df.get("Status", "").str.lower() != args.not_status.strip().lower()]

    # Contains filters
    if args.contains:
        df = apply_contains(df, args.contains)

    # Optional date window
    if (args.date_from or args.date_to) and args.date_col:
        col = args.date_col
        if col in df.columns:
            dates = pd.to_datetime(df[col], errors="coerce")
            if args.date_from:
                start = pd.to_datetime(args.date_from + " 00:00:00", errors="coerce")
                df = df[dates >= start]
            if args.date_to:
                end = pd.to_datetime(args.date_to + " 23:59:59", errors="coerce")
                df = df[dates <= end]
        else:
            print(f"[WARN] --date-col '{col}' not found in CSV. Skipping date filter.", file=sys.stderr)

    # Optional nesting of Question/Answer pairs
    if args.nest_qa:
        # Build a new DataFrame with QA nested, drop original Q/A cols
        static_cols = [
            c for c in df.columns
            if not c.lower().startswith("question ")
            and not c.lower().startswith("answer ")
        ]
        nested = df[static_cols].copy()
        nested["qa"] = df.apply(build_qa_nested, axis=1)
        df = nested

    # keep-cols selection (works for both flat and nested cases; 'qa' is a valid column if --nest-qa)
    if args.keep_cols:
        try:
            df = select_cols(df, args.keep_cols)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 4

    # Optional limit
    if args.limit is not None and args.limit >= 0:
        df = df.head(args.limit)

    out_rows = len(df)
    print(f"[INFO] Rows in: {in_rows}  →  Rows out: {out_rows}")

    # Write JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # If nested (qa column), convert rows to dicts carefully
    if args.nest_qa:
        records = []
        for _, row in df.iterrows():
            rec = {}
            for c in df.columns:
                rec[c] = row[c]
            records.append(rec)
        data = records
    else:
        data = json.loads(df.to_json(orient="records", force_ascii=False))

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Wrote JSON: {output_path}")
    return 0


#========================================================+=========================================#
'''
Run Script
'''
if __name__ == "__main__":
    # sys.exit(main())
    main()
