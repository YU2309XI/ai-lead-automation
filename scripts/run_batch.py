"""Classify a JSON file of leads and write a Google Sheets ready CSV.

Usage:
    python scripts/run_batch.py
    python scripts/run_batch.py --input sample-data/leads.json --output output/leads.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from classifier import classify_lead  # noqa: E402

COLUMNS = [
    "received_at",
    "name",
    "company",
    "email",
    "category",
    "priority",
    "lead_quality",
    "budget_hint",
    "summary",
    "suggested_reply",
    "message",
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sample-data/leads.json")
    parser.add_argument("--output", default="output/leads.csv")
    return parser.parse_args()


def main():
    args = parse_args()

    with open(args.input, encoding="utf-8") as handle:
        leads = json.load(handle)

    if isinstance(leads, dict):
        leads = [leads]

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []

    for lead in leads:
        record = classify_lead(lead)
        record["received_at"] = timestamp
        rows.append({column: record.get(column, "") for column in COLUMNS})
        print(
            f"{record['lead_quality']:<13} {record['priority']:<7} "
            f"{record['category']:<17} {record.get('name', '')}"
        )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    qualified = sum(1 for row in rows if row["lead_quality"] == "Qualified")
    print(f"\n{len(rows)} leads processed, {qualified} qualified")
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
