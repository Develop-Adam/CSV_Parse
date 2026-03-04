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
CLI Args
- Adds --profile to select which layout from settings.json to use
- Defaults for person/id/status columns come from the selected profile's "reporting" section
  (but CLI args still override)
'''
def build_parser():
    p = argparse.ArgumentParser(
        description="Grade completion performance by person (Completed by) based on missing answers."
    )

    p.add_argument("--input", default="inputs/filtered.json", help="Input JSON (default: inputs/filtered.json)")
    p.add_argument("--output", default="outputs/completed_by_grades.csv",
                   help="Output CSV (default: outputs/completed_by_grades.csv)")
    p.add_argument("--settings", default="inputs/settings.json", help="Settings JSON (default: inputs/settings.json)")
    p.add_argument("--profile", default=None, help="Profile name inside settings.json (defaults to default_profile)")

    # Column overrides (if omitted, we will pull from profile.reporting)
    p.add_argument("--person-col", default=None, help="Column containing person name")
    p.add_argument("--id-col", default=None, help="Work order identifier column")
    p.add_argument("--status-col", default=None, help="Optional status column")

    # Optional: grade only specific statuses (repeatable)
    p.add_argument("--only-status", action="append", default=[],
                   help="Only include work orders where Status == value (repeatable)")

    # How to treat blank question text
    p.add_argument("--blank-question", choices=["ignore", "count"], default="ignore",
                   help="If question text is blank, ignore it or count it (default: ignore)")

    # Nested QA support (if your JSON was produced with --nest-qa)
    p.add_argument("--nested-qa", action="store_true",
                   help="Input JSON contains qa array of {number, question, answer} objects")

    # Score -> Letter grade thresholds
    p.add_argument("--a", type=float, default=95.0, help="A threshold percent (default: 95)")
    p.add_argument("--b", type=float, default=90.0, help="B threshold percent (default: 90)")
    p.add_argument("--c", type=float, default=80.0, help="C threshold percent (default: 80)")
    p.add_argument("--d", type=float, default=70.0, help="D threshold percent (default: 70)")

    # Output detail
    p.add_argument("--include-top-missing", type=int, default=5,
                   help="Include top N most-missed question numbers per person (default: 5)")

    return p


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
Compute grades per person for a "flat" JSON format:
records contain columns like Question_1, Answer_1, etc.

Outputs a DataFrame with one row per person:
- workorders_count
- questions_total
- answers_filled
- answers_missing
- completion_percent
- grade
- top_missed_questions
'''
def compute_flat_person_grades(
    df: pd.DataFrame,
    qa_pairs: List[Tuple[str, str, str]],
    person_col: str,
    id_col: str,
    status_col: str,
    only_status: List[str],
    blank_question_mode: str,
    grade_thresholds: Tuple[float, float, float, float],
    include_top_missing: int,
) -> pd.DataFrame:
    a_thr, b_thr, c_thr, d_thr = grade_thresholds

    # Optional status filter
    if only_status and status_col in df.columns:
        allowed = {s.strip().lower() for s in only_status if s.strip()}
        df = df[df[status_col].astype(str).str.lower().isin(allowed)]

    # Aggregation buckets
    by_person: Dict[str, Dict[str, int]] = {}
    missed_counts: Dict[str, Dict[str, int]] = {}  # person -> question_num -> missed_count

    for _, r in df.iterrows():
        person = clean_str(r.get(person_col, "")) or "(blank)"

        if person not in by_person:
            by_person[person] = {
                "workorders": 0,
                "questions_total": 0,
                "answers_filled": 0,
                "answers_missing": 0,
            }
            missed_counts[person] = {}

        by_person[person]["workorders"] += 1

        for n, q_col, a_col in qa_pairs:
            q = clean_str(r.get(q_col, ""))
            a = clean_str(r.get(a_col, ""))

            # If question text is blank, optionally ignore that slot
            if not q and blank_question_mode == "ignore":
                continue

            by_person[person]["questions_total"] += 1
            if a:
                by_person[person]["answers_filled"] += 1
            else:
                by_person[person]["answers_missing"] += 1
                missed_counts[person][n] = missed_counts[person].get(n, 0) + 1

    # Build output
    out_rows = []
    for person, s in by_person.items():
        total = s["questions_total"]
        filled = s["answers_filled"]
        pct = (filled / total * 100.0) if total else 100.0
        grade = letter_grade(pct, a_thr, b_thr, c_thr, d_thr)

        # Top missed questions for this person
        misses = missed_counts.get(person, {})
        top = sorted(misses.items(), key=lambda kv: (-kv[1], kv[0]))
        top = top[: max(0, include_top_missing)]
        top_str = ", ".join([f"{num}({cnt})" for num, cnt in top])

        out_rows.append({
            person_col: person,
            "workorders_count": s["workorders"],
            "questions_total": total,
            "answers_filled": filled,
            "answers_missing": s["answers_missing"],
            "completion_percent": round(pct, 2),
            "grade": grade,
            "top_missed_questions": top_str,
        })

    out = pd.DataFrame(out_rows)
    if not out.empty:
        out = out.sort_values(by=["completion_percent", "workorders_count"], ascending=[False, False])
    return out


#========================================================+=========================================#
'''
Compute grades per person for a "nested" JSON format:
each record contains:
  qa: [ {number, question, answer}, ... ]

Outputs the same shape as compute_flat_person_grades.
'''
def compute_nested_person_grades(
    records: List[dict],
    person_col: str,
    id_col: str,
    status_col: str,
    only_status: List[str],
    blank_question_mode: str,
    grade_thresholds: Tuple[float, float, float, float],
    include_top_missing: int,
) -> pd.DataFrame:
    a_thr, b_thr, c_thr, d_thr = grade_thresholds
    allowed = {s.strip().lower() for s in only_status if s.strip()} if only_status else None

    by_person: Dict[str, Dict[str, int]] = {}
    missed_counts: Dict[str, Dict[str, int]] = {}

    for rec in records:
        # optional status filter
        if allowed and clean_str(rec.get(status_col, "")).lower() not in allowed:
            continue

        person = clean_str(rec.get(person_col, "")) or "(blank)"

        if person not in by_person:
            by_person[person] = {
                "workorders": 0,
                "questions_total": 0,
                "answers_filled": 0,
                "answers_missing": 0,
            }
            missed_counts[person] = {}

        by_person[person]["workorders"] += 1

        qa_list = rec.get("qa", [])
        if not isinstance(qa_list, list):
            qa_list = []

        for item in qa_list:
            if not isinstance(item, dict):
                continue
            n = clean_str(item.get("number", ""))
            q = clean_str(item.get("question", ""))
            a = clean_str(item.get("answer", ""))

            if not q and blank_question_mode == "ignore":
                continue

            by_person[person]["questions_total"] += 1
            if a:
                by_person[person]["answers_filled"] += 1
            else:
                by_person[person]["answers_missing"] += 1
                if n:
                    missed_counts[person][n] = missed_counts[person].get(n, 0) + 1

    out_rows = []
    for person, s in by_person.items():
        total = s["questions_total"]
        filled = s["answers_filled"]
        pct = (filled / total * 100.0) if total else 100.0
        grade = letter_grade(pct, a_thr, b_thr, c_thr, d_thr)

        misses = missed_counts.get(person, {})
        top = sorted(misses.items(), key=lambda kv: (-kv[1], kv[0]))[: max(0, include_top_missing)]
        top_str = ", ".join([f"{num}({cnt})" for num, cnt in top])

        out_rows.append({
            person_col: person,
            "workorders_count": s["workorders"],
            "questions_total": total,
            "answers_filled": filled,
            "answers_missing": s["answers_missing"],
            "completion_percent": round(pct, 2),
            "grade": grade,
            "top_missed_questions": top_str,
        })

    out = pd.DataFrame(out_rows)
    if not out.empty:
        out = out.sort_values(by=["completion_percent", "workorders_count"], ascending=[False, False])
    return out


#========================================================+=========================================#
'''
Main
- loads settings.json
- selects profile
- pulls default reporting column names from profile.reporting
- loads JSON records
- computes grades (flat or nested)
- writes CSV output
'''
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    input_path = resolve_path(script_dir, args.input)
    output_path = resolve_path(script_dir, args.output)
    settings_path = resolve_path(script_dir, args.settings)

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
    person_col = args.person_col or reporting.get("person_col") or "Completed by"
    id_col = args.id_col or reporting.get("id_col") or "WorkOrder"
    status_col = args.status_col or reporting.get("status_col") or "Status"

    # Load header from profile for QA detection (flat mode)
    csv_settings = (profile or {}).get("csv", {})
    header = csv_settings.get("header", [])
    if not isinstance(header, list):
        header = []

    # Load JSON
    try:
        records = load_json_records(input_path)
    except Exception as e:
        print(f"[ERROR] Failed to read JSON: {e}", file=sys.stderr)
        return 4

    thresholds = (args.a, args.b, args.c, args.d)

    if args.nested_qa:
        report_df = compute_nested_person_grades(
            records=records,
            person_col=person_col,
            id_col=id_col,
            status_col=status_col,
            only_status=args.only_status,
            blank_question_mode=args.blank_question,
            grade_thresholds=thresholds,
            include_top_missing=args.include_top_missing,
        )
    else:
        qa_pairs = extract_qa_pairs_from_header(header)
        if not qa_pairs:
            print("[ERROR] Could not find any Question/Answer pairs from profile csv.header.", file=sys.stderr)
            print("        Expected columns like Question_1 and Answer_1 (or Question 1 / Answer 1).", file=sys.stderr)
            return 5

        df = pd.DataFrame.from_records(records)
        report_df = compute_flat_person_grades(
            df=df,
            qa_pairs=qa_pairs,
            person_col=person_col,
            id_col=id_col,
            status_col=status_col,
            only_status=args.only_status,
            blank_question_mode=args.blank_question,
            grade_thresholds=thresholds,
            include_top_missing=args.include_top_missing,
        )

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_path, index=False, encoding="utf-8")

    # Quick summary
    print(f"[INFO] Wrote report: {output_path}")
    if not report_df.empty:
        avg = report_df["completion_percent"].mean()
        print(f"[INFO] People: {len(report_df)}  Average completion: {avg:.2f}%")
    else:
        print("[INFO] No rows to report (check filters/status/person column).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
