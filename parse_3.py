#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd

#========================================================+=========================================#
'''
Constants
'''
# Used by clean_str to normalize whitespace
NBSP = "\u00A0"


#========================================================+=========================================#
'''
    normalize values to a safe string:
    - None or NaN -> ""
    - convert to string
    - replace NBSP with normal spaces
    - strip surrounding whitespace
'''
def clean_str(x) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x).replace(NBSP, " ").strip()


#========================================================+=========================================#
'''
Load settings JSON from disk.
Expected format:
{
  "default_profile": "layout_A",
  "profiles": {
    "layout_A": { "csv": {...}, "reporting": {...} },
    "layout_B": { "csv": {...}, "reporting": {...} }
  }
}
'''
def load_settings(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


#========================================================+=========================================#
'''
Select a profile from the loaded settings, using:
- --profile if provided
- else settings["default_profile"]
- else the first profile in settings["profiles"]
'''
def select_profile(settings: dict, profile_name: str | None) -> tuple[str, dict]:
    profiles = (settings or {}).get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("settings.json must contain a top-level 'profiles' object")

    if profile_name:
        if profile_name not in profiles:
            raise ValueError(f"Profile '{profile_name}' not found. Available: {list(profiles.keys())}")
        return profile_name, profiles[profile_name]

    default_name = (settings or {}).get("default_profile")
    if default_name and default_name in profiles:
        return default_name, profiles[default_name]

    first = next(iter(profiles.keys()))
    return first, profiles[first]


#========================================================+=========================================#
'''
Resolve a path relative to the script directory unless it is already absolute.
'''
def resolve_path(script_dir: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (script_dir / path).resolve()


#========================================================+=========================================#
'''
Load JSON records from disk.
Accepts:
- list[dict] (preferred)
- dict containing a list under keys: records, data, items
'''
def load_json_records(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("records", "data", "items"):
            if isinstance(data.get(k), list):
                return data[k]
    raise ValueError("JSON root must be a list of objects (or dict containing list under records/data/items).")


#========================================================+=========================================#
'''
Extract Question/Answer column pairs from the selected profile's CSV header.

Supports:
- Question_1 + Answer_1
- Question 1 + Answer 1

Returns:
[(question_number, question_col_name, answer_col_name), ...]
'''
def extract_qa_pairs_from_header(header: List[str]) -> List[Tuple[str, str, str]]:
    lower_to_orig = {str(c).lower(): c for c in header}

    def find_col(name_variants: List[str]) -> Optional[str]:
        for v in name_variants:
            k = v.lower()
            if k in lower_to_orig:
                return lower_to_orig[k]
        return None

    nums = set()
    for c in header:
        s = str(c)
        sl = s.lower()
        if sl.startswith("question_"):
            nums.add(s.split("_", 1)[1])
        elif sl.startswith("question "):
            nums.add(s.split(" ", 1)[1])

    pairs: List[Tuple[str, str, str]] = []
    for n in sorted(nums, key=lambda x: (len(str(x)), str(x))):
        q = find_col([f"Question_{n}", f"Question {n}"])
        a = find_col([f"Answer_{n}", f"Answer {n}"])
        if q and a:
            pairs.append((str(n), q, a))
    return pairs


#========================================================+=========================================#
'''
Convert a completion percent into a letter grade.
'''
def letter_grade(pct: float, a: float, b: float, c: float, d: float) -> str:
    if pct >= a:
        return "A"
    if pct >= b:
        return "B"
    if pct >= c:
        return "C"
    if pct >= d:
        return "D"
    return "F"


#========================================================+=========================================#
'''
CLI Args
- Adds --profile to select which layout from settings.json to use
- Defaults for status/id columns can come from the selected profile's "reporting" section
  (but CLI args still override)
'''
def build_parser():
    p = argparse.ArgumentParser(
        description="Grade the entire work order set as an average, plus per-question completion breakdown."
    )

    p.add_argument("--input", default="inputs/filtered.json", help="Input JSON (default: inputs/filtered.json)")
    p.add_argument("--settings", default="inputs/settings.json", help="Settings JSON (default: inputs/settings.json)")
    p.add_argument("--profile", default=None, help="Profile name inside settings.json (defaults to default_profile)")

    # Output files (two reports)
    p.add_argument("--summary-out", default="outputs/workorder_set_summary.csv",
                   help="Summary CSV (default: outputs/workorder_set_summary.csv)")
    p.add_argument("--question-out", default="outputs/question_completion_breakdown.csv",
                   help="Per-question breakdown CSV (default: outputs/question_completion_breakdown.csv)")

    # Optional filters (can be defaulted from profile.reporting)
    p.add_argument("--status-col", default=None, help="Status column name")
    p.add_argument("--only-status", action="append", default=[],
                   help="Only include work orders where Status == value (repeatable)")

    # Identity columns (can be defaulted from profile.reporting)
    p.add_argument("--id-col", default=None, help="Work order ID column")

    # Treat blank question text
    p.add_argument("--blank-question", choices=["ignore", "count"], default="ignore",
                   help="If question text is blank, ignore it or count it (default: ignore)")

    # Nested QA support
    p.add_argument("--nested-qa", action="store_true",
                   help="Input JSON contains qa array of {number, question, answer} objects")

    # Grade thresholds
    p.add_argument("--a", type=float, default=95.0, help="A threshold percent (default: 95)")
    p.add_argument("--b", type=float, default=90.0, help="B threshold percent (default: 90)")
    p.add_argument("--c", type=float, default=80.0, help="C threshold percent (default: 80)")
    p.add_argument("--d", type=float, default=70.0, help="D threshold percent (default: 70)")

    return p


#========================================================+=========================================#
'''
Filter a DataFrame to only include rows where status_col matches one of only_status.
'''
def apply_status_filter_df(df: pd.DataFrame, status_col: str, only_status: List[str]) -> pd.DataFrame:
    if not only_status:
        return df
    if status_col not in df.columns:
        return df
    allowed = {s.strip().lower() for s in only_status if s.strip()}
    return df[df[status_col].astype(str).str.lower().isin(allowed)]


#========================================================+=========================================#
'''
Filter a list of JSON records to only include items where status_col matches one of only_status.
'''
def apply_status_filter_records(records: List[dict], status_col: str, only_status: List[str]) -> List[dict]:
    if not only_status:
        return records
    allowed = {s.strip().lower() for s in only_status if s.strip()}
    return [r for r in records if clean_str(r.get(status_col, "")).lower() in allowed]


#========================================================+=========================================#
'''
Compute summary + per-question breakdown for flat JSON records.

Flat format means each record has columns like:
  Question_1, Answer_1, Question_2, Answer_2, ...

Returns:
- summary dict (overall completion for the whole set)
- q_df DataFrame (completion per question number)
'''
def compute_flat_set_reports(
    df: pd.DataFrame,
    qa_pairs: List[Tuple[str, str, str]],
    id_col: str,
    blank_question_mode: str,
) -> Tuple[Dict, pd.DataFrame]:
    workorders = df[id_col].nunique() if id_col in df.columns else len(df)

    total_questions = 0
    total_answered = 0

    # Per question counters: n -> {total, answered}
    q_stats: Dict[str, Dict[str, int]] = {n: {"total": 0, "answered": 0} for n, _, _ in qa_pairs}

    for _, r in df.iterrows():
        for n, q_col, a_col in qa_pairs:
            q = clean_str(r.get(q_col, ""))
            a = clean_str(r.get(a_col, ""))

            # If question text is blank, optionally ignore that slot
            if not q and blank_question_mode == "ignore":
                continue

            total_questions += 1
            q_stats[n]["total"] += 1

            if a:
                total_answered += 1
                q_stats[n]["answered"] += 1

    completion_pct = (total_answered / total_questions * 100.0) if total_questions else 100.0

    # Per-question breakdown rows
    rows = []
    for n, q_col, a_col in qa_pairs:
        t = q_stats[n]["total"]
        ans = q_stats[n]["answered"]
        pct = (ans / t * 100.0) if t else 100.0
        rows.append({
            "question_number": n,
            "question_col": q_col,
            "answer_col": a_col,
            "instances_counted": t,
            "instances_answered": ans,
            "instances_missing": t - ans,
            "completion_percent": round(pct, 2),
        })

    q_df = pd.DataFrame(rows).sort_values(by="question_number", key=lambda s: s.astype(str))

    summary = {
        "workorders_count": int(workorders),
        "questions_total": int(total_questions),
        "answers_filled": int(total_answered),
        "answers_missing": int(total_questions - total_answered),
        "completion_percent": round(completion_pct, 2),
    }

    return summary, q_df


#========================================================+=========================================#
'''
Compute summary + per-question breakdown for nested JSON records.

Nested format means each record has:
  qa: [ {number, question, answer}, ... ]

Returns:
- summary dict (overall completion for the whole set)
- q_df DataFrame (completion per question number)
'''
def compute_nested_set_reports(
    records: List[dict],
    blank_question_mode: str,
) -> Tuple[Dict, pd.DataFrame]:
    workorders = len(records)

    total_questions = 0
    total_answered = 0

    # n -> {total, answered}
    q_stats: Dict[str, Dict[str, int]] = {}

    for rec in records:
        qa_list = rec.get("qa", [])
        if not isinstance(qa_list, list):
            continue

        for item in qa_list:
            if not isinstance(item, dict):
                continue

            n = clean_str(item.get("number", ""))
            q = clean_str(item.get("question", ""))
            a = clean_str(item.get("answer", ""))

            if not q and blank_question_mode == "ignore":
                continue

            if not n:
                n = "(unknown)"

            if n not in q_stats:
                q_stats[n] = {"total": 0, "answered": 0}

            total_questions += 1
            q_stats[n]["total"] += 1

            if a:
                total_answered += 1
                q_stats[n]["answered"] += 1

    completion_pct = (total_answered / total_questions * 100.0) if total_questions else 100.0

    rows = []
    for n, s in q_stats.items():
        t = s["total"]
        ans = s["answered"]
        pct = (ans / t * 100.0) if t else 100.0
        rows.append({
            "question_number": n,
            "instances_counted": t,
            "instances_answered": ans,
            "instances_missing": t - ans,
            "completion_percent": round(pct, 2),
        })

    q_df = pd.DataFrame(rows)

    # Sort question numbers naturally if possible
    if not q_df.empty:
        def sort_key(val: str):
            try:
                return (0, int(val))
            except Exception:
                return (1, val)
        q_df = q_df.sort_values(by="question_number", key=lambda s: s.map(sort_key))

    summary = {
        "workorders_count": int(workorders),
        "questions_total": int(total_questions),
        "answers_filled": int(total_answered),
        "answers_missing": int(total_questions - total_answered),
        "completion_percent": round(completion_pct, 2),
    }
    return summary, q_df


#========================================================+=========================================#
'''
Main
- loads settings.json
- selects profile
- pulls default id/status columns from profile.reporting
- loads JSON
- computes overall completion + per-question breakdown (flat or nested)
- writes two CSV outputs
'''
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    input_path = resolve_path(script_dir, args.input)
    settings_path = resolve_path(script_dir, args.settings)
    summary_out = resolve_path(script_dir, args.summary_out)
    question_out = resolve_path(script_dir, args.question_out)

    if not input_path.exists():
        print(f"[ERROR] Input JSON not found: {input_path}", file=sys.stderr)
        return 2

    # Load settings + select profile
    try:
        settings = load_settings(settings_path)
        profile_name, profile = select_profile(settings, args.profile)
    except Exception as e:
        print(f"[ERROR] Failed to load/select profile: {e}", file=sys.stderr)
        return 3

    print(f"[INFO] Using settings: {settings_path}  profile: {profile_name}")

    # Pull default columns from profile.reporting, allow CLI overrides
    reporting = (profile or {}).get("reporting", {})
    status_col = args.status_col or reporting.get("status_col") or "Status"
    id_col = args.id_col or reporting.get("id_col") or "WorkOrder"

    # Load header from profile for QA detection (flat mode)
    csv_settings = (profile or {}).get("csv", {})
    header = csv_settings.get("header", [])
    if not isinstance(header, list):
        header = []

    # Load JSON records
    try:
        records = load_json_records(input_path)
    except Exception as e:
        print(f"[ERROR] Failed to read JSON: {e}", file=sys.stderr)
        return 4

    # Filter by status if requested (works for both flat and nested)
    if args.only_status:
        records = apply_status_filter_records(records, status_col, args.only_status)

    thresholds = (args.a, args.b, args.c, args.d)

    if args.nested_qa:
        summary, q_df = compute_nested_set_reports(
            records=records,
            blank_question_mode=args.blank_question,
        )
    else:
        qa_pairs = extract_qa_pairs_from_header(header)
        if not qa_pairs:
            print("[ERROR] Could not find any Question/Answer pairs from profile csv.header.", file=sys.stderr)
            print("        Expected columns like Question_1 and Answer_1 (or Question 1 / Answer 1).", file=sys.stderr)
            return 5

        df = pd.DataFrame.from_records(records)
        df = apply_status_filter_df(df, status_col, args.only_status)

        summary, q_df = compute_flat_set_reports(
            df=df,
            qa_pairs=qa_pairs,
            id_col=id_col,
            blank_question_mode=args.blank_question,
        )

    # Add grade to summary
    summary_pct = float(summary.get("completion_percent", 0.0))
    summary["grade"] = letter_grade(summary_pct, *thresholds)

    # Write outputs
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    question_out.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([summary]).to_csv(summary_out, index=False, encoding="utf-8")
    q_df.to_csv(question_out, index=False, encoding="utf-8")

    print(f"[INFO] Wrote summary:   {summary_out}")
    print(f"[INFO] Wrote breakdown: {question_out}")
    print(f"[INFO] Set completion: {summary['completion_percent']}%  Grade: {summary['grade']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
