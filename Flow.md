# Program Flow

## Each chart describes the logic of each python script

### filter_work_orders_to_json.py

```mermaid
flowchart TD
    A[Start] --> B[Parse CLI args<br/>--input, --output, --status, --not-status,<br/>--date-col, --date-from/to, --contains, --keep-cols, --limit]
    B --> C["Resolve input/output paths<br/>(absolute; relative to script if needed)"]
    C --> D{Input CSV exists?}
    D -- No --> E["[Exit with error: file not found]"]
    D -- Yes --> F["Read CSV with pandas (dtype=str, keep_default_na=False)"]
    F --> G["Whitespace clean across all columns<br/>(trim + remove NBSP)"]
    G --> H{--status set?}
    H -- Yes --> I["Filter df where Status == value (case-insensitive)"]
    H -- No --> J[Skip]
    I --> K
    J --> K{--not-status set?}
    K -- Yes --> L[Exclude rows where Status == value]
    K -- No --> M[Skip]
    L --> N
    M --> N{Any --contains rules?}
    N -- Yes --> O["For each rule 'Col::substr':<br/>df[col] contains substr (case-insensitive)"]
    N -- No --> P[Skip]
    O --> Q
    P --> Q{Date filter requested AND date column present?}
    Q -- Yes --> R["Parse df[date_col] to datetime;<br/>apply date_from/to inclusive"]
    Q -- No --> S[Skip]
    R --> T{--keep-cols provided?}
    S --> T
    T -- Yes --> U[Select only listed columns]
    T -- No --> V[Keep all columns]
    U --> W{--limit provided?}
    V --> W{--limit provided?}
    W -- Yes --> X["df = df.head(limit)"]
    W -- No --> Y[Skip]
    X --> Z["Write JSON (records, pretty)"]
    Y --> Z["Write JSON (records, pretty)"]
    Z --> AA["[Print rows in/out; Exit 0]"]
```

# score_from_json_auto.py

```mermaid
flowchart TD
    A[Start] --> B["Set constants:<br/>INPUT=filtered.json,<br/>outputs for WO & Person (JSON/CSV)"]
    B --> C{filtered.json exists?}
    C -- No --> D["[Exit with error: missing input]"]
    C -- Yes --> E["Load JSON → DataFrame (list of records)"]
    E --> F["Clean strings in all columns<br/>(trim + remove NBSP)"]
    F --> G{Has 'qa' column?}
    G -- Yes --> H[Per row: count answers from nested qa list]
    G -- No --> I[Per row: count answers from flat 'Answer N' columns]
    H --> J
    I --> J[Compute per‑work‑order metrics:<br/>AnswersCompleted, TotalQuestions, CompletionPct;<br/>keep ID, Title, Status, Person]
    J --> K["Detect person column (Assigned/Completed by/etc.)<br/>fallback 'Person'='Unassigned'"]
    K --> L["Build wo_df (one row per work order)"]
    L --> M{wo_df empty?}
    M -- Yes --> N[Create empty person_df with expected columns]
    M -- No --> O[Group by Person → Orders, AnswersCompleted_Total,<br/>AnswersCompleted_Avg, CompletionPct_Avg]
    O --> P[Compute Score = AnswersCompleted_Total;<br/>round averages]
    N --> Q
    P --> Q[Write outputs:<br/>work_order_scores.json + .csv<br/>person_scores.json + .csv]
    Q --> R["[Print success; Exit 0]"]
```

## qa_miss_breakdown_auto.py

```mermaid
flowchart TD
    A[Start] --> B["Set constants:<br/>INPUT=filtered.json,<br/>output filenames for overall/by-person/by-order (JSON/CSV)"]
    B --> C{filtered.json exists?}
    C -- No --> D["[Exit with error: missing input]"]
    C -- Yes --> E[Load JSON → DataFrame]
    E --> F["Clean strings<br/>(trim + remove NBSP)"]
    F --> G["Detect person column (Assigned/Completed/etc.)<br/>fallback 'Person'='Unassigned'"]
    G --> H{Has 'qa' column?}
    H -- Yes --> I["Extractor = nested: (number, question, answer)"]
    H -- No --> J["Extractor = flat: (number, question, answer) from Question/Answer N"]
    I --> K
    J --> K["Per row (work order): build asked list; collect missed where answer ∈ {empty, N/A, -, na, null, none}"]
    K --> L["Create by_order_df with:<br/>ID, Title, Status, Person, TotalQuestionsAsked,<br/>MissedCount, MissedQuestions (joined)"]
    L --> M["Normalize all Q/A into long table:<br/>(Number, Question, Missed(0/1), Person)"]
    M --> N{long table empty?}
    N -- Yes --> O[overall_df & by_person_df = empty frames]
    N -- No --> P["Overall: group by (Number, Question) → Asked, Missed, MissRatePct;<br/>sort by Missed desc, MissRatePct desc"]
    P --> Q["By‑person: group by (Person, Number, Question) → Asked, Missed, MissRatePct;<br/>sort by Person then Missed desc"]
    O --> R
    Q --> R[Write outputs:<br/>qa_miss_overall.json/.csv,<br/>qa_miss_by_person.json/.csv,<br/>qa_miss_by_order.json/.csv]
    R --> S["[Print success; Exit 0]"]

```

