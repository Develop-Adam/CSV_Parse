#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUTO REPORT: Which questions are missed most often?
---------------------------------------------------
Reads filtered.json (produced by your earlier step) and outputs:
  1) Overall miss frequency per question
  2) Per-person miss frequency per question
  3) Per-work-order list of missed questions

NO inputs required. Just run:  python qa_miss_breakdown_auto.py
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pandas as pd

# ----------------- Config (edit if you need) -----------------
INPUT_FILE = "inputs/filtered.json"

OVERALL_JSON = "records_JSON/qa_miss_overall.json"
OVERALL_CSV  = "records_CSV/qa_miss_overall.csv"

BY_PERSON_JSON = "records_JSON/qa_miss_by_person.json"
BY_PERSON_CSV  = "records_CSV/qa_miss_by_person.csv"

BY_ORDER_JSON = "records_JSON/qa_miss_by_order.json"
BY_ORDER_CSV  = "records_CSV/qa_miss_by_order.csv"

# Values considered NOT answered (case-insensitive after trimming)
PLACEHOLDER_MISSING = {"", "n/a", "-", "na", "null", "none"}

# Candidate columns that identify the person assigned/completing
PERSON_COL_CANDIDATES = [
    "Assigned to", "Assigned To", "Assigned",
    "Completed by", "Completed By",
    "Employees", "Employees Involved",
    "Task Lead", "Task Lead Signature",
    "Technician", "Owner", "Responsible"
]
# -------------------------------------------------------------

NBSP = "\u00A0"

def clean_str(x: Any) -> str:
    if pd.isna(x):
        return ""
    return str(x).replace(NBSP, " ").strip()

def is_missing(x: Any) -> bool:
    s = clean_str(x).lower()
    return s in PLACEHOLDER_MISSING

def detect_person_col(cols: List[str]) -> str:
    lower = {c.lower(): c for c in cols}
    for want in PERSON_COL_CANDIDATES:
        if want.lower() in lower:
            return lower[want.lower()]
    return ""  # not found

def iter_qa_pairs_from_flat(row: pd.Series) -> List[Tuple[str, str, str]]:
    """
    From a flat row with 'Question N' / 'Answer N' columns,
    return a list of tuples: (number, question_text, answer_text).
    """
    pairs: List[Tuple[str, str, str]] = []
    for col in row.index:
        name = col.lower()
        if name.startswith("answer "):
            num = col.split(" ", 1)[1].strip()
            a = clean_str(row[col])
            q_col = f"Question {num}"
            q = clean_str(row.get(q_col, ""))
            # Consider a question "asked" if it has a question text OR an answer present
            if q or a:
                pairs.append((num, q, a))
    return pairs

def iter_qa_pairs_from_nested(qa: Any) -> List[Tuple[str, str, str]]:
    """
    From a nested 'qa' array with dicts ({number, question, answer}),
    return (number, question_text, answer_text).
    """
    out: List[Tuple[str, str, str]] = []
    if not isinstance(qa, list):
        return out
    for item in qa:
        num = clean_str(item.get("number", ""))
        q = clean_str(item.get("question", ""))
        a = clean_str(item.get("answer", ""))
        if q or a:
            out.append((num, q, a))
    return out

def main():
    here = Path(__file__).resolve().parent
    in_path = here / INPUT_FILE

    if not in_path.exists():
        print(f"[ERROR] Cannot find {INPUT_FILE} next to this script: {in_path}")
        return

    with in_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("[ERROR] Input JSON must be a list of objects (records).")
        return

    df = pd.DataFrame(data)
    # Clean all string-like fields
    for c in df.columns:
        df[c] = df[c].apply(clean_str)

    # Person column
    person_col = detect_person_col(list(df.columns))
    if not person_col:
        person_col = "Person"
        df[person_col] = "Unassigned"

    # Detect QA structure
    has_nested = "qa" in df.columns

    # ----------------- Per-order misses -----------------
    by_order_records: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        wo_id    = row.get("ID", "")
        title    = row.get("Title", "")
        status   = row.get("Status", "")
        person   = row.get(person_col, "") or "Unassigned"

        # Extract Q/A pairs
        if has_nested:
            qa_pairs = iter_qa_pairs_from_nested(row.get("qa", []))
        else:
            qa_pairs = iter_qa_pairs_from_flat(row)

        # Determine which were "asked"
        asked_pairs = [(n, q, a) for (n, q, a) in qa_pairs if (q or a)]
        missed = [(n, q) for (n, q, a) in asked_pairs if is_missing(a)]

        by_order_records.append({
            "ID": wo_id,
            "Title": title,
            "Status": status,
            "Person": person,
            "TotalQuestionsAsked": len(asked_pairs),
            "MissedCount": len(missed),
            # Join both the number and (short) question text for readability
            "MissedQuestions": "; ".join(
                [f"{n or '?'}: {q[:80]}" if q else f"{n or '?'}"
                 for (n, q) in missed]
            )
        })

    by_order_df = pd.DataFrame(by_order_records)

    # ----------------- Overall question miss stats -----------------
    # Build a normalized long table of (number, question, missed [0/1], person)
    long_rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        person = row.get(person_col, "") or "Unassigned"
        if has_nested:
            qa_pairs = iter_qa_pairs_from_nested(row.get("qa", []))
        else:
            qa_pairs = iter_qa_pairs_from_flat(row)

        for (n, q, a) in qa_pairs:
            if not (q or a):
                continue  # not actually asked
            long_rows.append({
                "Number": n,
                "Question": q,
                "Missed": 1 if is_missing(a) else 0,
                "Person": person
            })

    long_df = pd.DataFrame(long_rows)

    if len(long_df) == 0:
        # Nothing to analyze
        overall_df = pd.DataFrame(columns=["Number", "Question", "Asked", "Missed", "MissRatePct"])
        by_person_df = pd.DataFrame(columns=["Person", "Number", "Question", "Asked", "Missed", "MissRatePct"])
    else:
        # Overall
        grp = long_df.groupby(["Number", "Question"], dropna=False)
        overall_df = pd.DataFrame({
            "Asked": grp.size(),
            "Missed": grp["Missed"].sum()
        }).reset_index()
        overall_df["MissRatePct"] = (overall_df["Missed"] / overall_df["Asked"] * 100).round(2)
        # Order by highest missed
        overall_df = overall_df.sort_values(["Missed", "MissRatePct", "Asked"], ascending=[False, False, False])

        # By person
        g2 = long_df.groupby(["Person", "Number", "Question"], dropna=False)
        by_person_df = pd.DataFrame({
            "Asked": g2.size(),
            "Missed": g2["Missed"].sum()
        }).reset_index()
        by_person_df["MissRatePct"] = (by_person_df["Missed"] / by_person_df["Asked"] * 100).round(2)
        by_person_df = by_person_df.sort_values(["Person", "Missed", "MissRatePct", "Asked"],
                                                ascending=[True, False, False, False])

    # ----------------- Write outputs (JSON + CSV) -----------------
    overall_df.to_csv(here / OVERALL_CSV, index=False, encoding="utf-8", lineterminator="\n")
    by_person_df.to_csv(here / BY_PERSON_CSV, index=False, encoding="utf-8", lineterminator="\n")
    by_order_df.to_csv(here / BY_ORDER_CSV, index=False, encoding="utf-8", lineterminator="\n")

    # (here / OVERALL_JSON).write_text(
    #     json.dumps(json.loads(overall_df.to_json(orient="records")), indent=2),
    #     encoding="utf-8"
    # )
    
    # (here / OVERALL_CSV).write_text(overall_df.to_csv(index=False), encoding="utf-8")

    # (here / BY_PERSON_JSON).write_text(
    #     json.dumps(json.loads(by_person_df.to_json(orient="records")), indent=2),
    #     encoding="utf-8"
    # )
    # (here / BY_PERSON_CSV).write_text(by_person_df.to_csv(index=False), encoding="utf-8")

    # (here / BY_ORDER_JSON).write_text(
    #     json.dumps(json.loads(by_order_df.to_json(orient="records")), indent=2),
    #     encoding="utf-8"
    # )
    # (here / BY_ORDER_CSV).write_text(by_order_df.to_csv(index=False), encoding="utf-8")
    
    # Console summary
    print(f"[OK] Wrote {OVERALL_JSON}, {OVERALL_CSV}")
    print(f"[OK] Wrote {BY_PERSON_JSON}, {BY_PERSON_CSV}")
    print(f"[OK] Wrote {BY_ORDER_JSON}, {BY_ORDER_CSV}")

if __name__ == "__main__":
    main()