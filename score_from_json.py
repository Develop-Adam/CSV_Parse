#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AUTO‑RUN SCORING SCRIPT (JSON + CSV OUTPUTS)
--------------------------------------------
Reads filtered.json, calculates:
  1) Per-work-order completion
  2) Per-person scores

NO user inputs required.
Just run:  python score_from_json_auto.py

Outputs (in the same folder as this script):
  - work_order_scores.json
  - work_order_scores.csv
  - person_scores.json
  - person_scores.csv
"""

import json
from pathlib import Path
import pandas as pd

NBSP = "\u00A0"

INPUT_FILE  = "inputs/filtered.json"
WO_JSON_OUT = "records_JSON/work_order_scores.json"
WO_CSV_OUT  = "records_CSV/work_order_scores.csv"
PERSON_JSON_OUT = "records_JSON/person_scores.json"
PERSON_CSV_OUT  = "records_CSV/person_scores.csv"

# ----------------- Utility Functions -----------------

def clean_str(x):
    if pd.isna(x):
        return ""
    return str(x).replace(NBSP, " ").strip()

def is_filled(x):
    s = clean_str(x)
    # Treat common placeholders as NOT completed
    return s not in ("", "N/A", "-", "na", "null", "none")

def detect_person_column(cols):
    candidates = [
        "Assigned to", "Assigned To", "Assigned",
        "Completed by", "Completed By",
        "Employees", "Employees Involved",
        "Task Lead", "Task Lead Signature",
    ]
    lower = {c.lower(): c for c in cols}
    for want in candidates:
        found = lower.get(want.lower())
        if found:
            return found
    return ""  # none found

def count_answers_flat(row):
    filled = 0
    total  = 0
    for col in row.index:
        if col.lower().startswith("answer "):
            total += 1
            if is_filled(row[col]):
                filled += 1
    return filled, total

def count_answers_nested(qa_list):
    if not isinstance(qa_list, list):
        return 0, 0
    total = len(qa_list)
    filled = sum(1 for item in qa_list if is_filled(item.get("answer", "")))
    return filled, total

# ----------------- Main Processing -----------------

def main():
    here = Path(__file__).resolve().parent
    json_path = here / INPUT_FILE

    if not json_path.exists():
        print(f"[ERROR] Cannot find {INPUT_FILE} next to this script: {json_path}")
        return

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Expect a list of objects
    if not isinstance(data, list):
        print("[ERROR] Input JSON must be a list of records (objects).")
        return

    df = pd.DataFrame(data)

    # Clean strings
    for c in df.columns:
        df[c] = df[c].apply(clean_str)

    has_nested = "qa" in df.columns

    # Determine person column (fallback to "Person")
    person_col = detect_person_column(df.columns)
    if not person_col:
        person_col = "Person"
        df[person_col] = "Unassigned"

    # ---- Per-work-order rows ----
    records = []
    for _, row in df.iterrows():
        if has_nested:
            filled, total = count_answers_nested(row.get("qa", []))
        else:
            filled, total = count_answers_flat(row)

        pct = (filled / total * 100) if total > 0 else 0.0

        rec = {
            "ID": row.get("ID", ""),
            "Title": row.get("Title", ""),
            "Status": row.get("Status", ""),
            "Person": row.get(person_col, "") or "Unassigned",
            "AnswersCompleted": int(filled),
            "TotalQuestions": int(total),
            "CompletionPct": round(pct, 2),
        }
        records.append(rec)

    wo_df = pd.DataFrame(records)

    # ---- Per-person aggregation ----
    if len(wo_df) == 0:
        person_df = pd.DataFrame(columns=[
            "Person", "Orders", "AnswersCompleted_Total",
            "AnswersCompleted_Avg", "CompletionPct_Avg", "Score"
        ])
    else:
        grp = wo_df.groupby("Person", dropna=False)
        person_df = pd.DataFrame({
            "Orders": grp.size(),
            "AnswersCompleted_Total": grp["AnswersCompleted"].sum(),
            "AnswersCompleted_Avg": grp["AnswersCompleted"].mean().round(2),
            "CompletionPct_Avg": grp["CompletionPct"].mean().round(2),
        }).reset_index()

        # Score = total completed answers (simple, additive)
        person_df["Score"] = person_df["AnswersCompleted_Total"]

    # ---- Write JSON files ----
    (here / WO_JSON_OUT).write_text(
        json.dumps(json.loads(wo_df.to_json(orient="records")), indent=2),
        encoding="utf-8"
    )
    (here / PERSON_JSON_OUT).write_text(
        json.dumps(json.loads(person_df.to_json(orient="records")), indent=2),
        encoding="utf-8"
    )

    # ---- Write CSV files ----
    wo_df.to_csv(here / WO_CSV_OUT, index=False, encoding="utf-8")
    person_df.to_csv(here / PERSON_CSV_OUT, index=False, encoding="utf-8")

    print(f"[OK] Wrote JSON: {WO_JSON_OUT}, {PERSON_JSON_OUT}")
    print(f"[OK] Wrote  CSV : {WO_CSV_OUT}, {PERSON_CSV_OUT}")

if __name__ == "__main__":
    main()