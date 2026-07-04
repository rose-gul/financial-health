"""ingest — read and normalize the transactions CSV into validated records."""

from __future__ import annotations

import csv
from datetime import date

from ..contracts import RunMeta
from ..guards import BoundaryValidationError
from ._base import log, run


def handler(_payload: dict, meta: RunMeta) -> dict:
    transactions = []
    with open(meta.csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"date", "description", "amount"}
        if not required.issubset({(h or "").strip() for h in (reader.fieldnames or [])}):
            raise BoundaryValidationError(
                f"CSV must have columns {sorted(required)}; got {reader.fieldnames}"
            )
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            raw_date = (row.get("date") or "").strip()
            raw_desc = (row.get("description") or "").strip()
            raw_amount = (row.get("amount") or "").strip()
            if not raw_date and not raw_desc and not raw_amount:
                continue  # skip blank lines
            try:
                parsed_date = date.fromisoformat(raw_date)
            except ValueError:
                raise BoundaryValidationError(
                    f"row {i}: date '{raw_date}' is not ISO format (YYYY-MM-DD)"
                )
            try:
                amount = round(float(raw_amount), 2)
            except ValueError:
                raise BoundaryValidationError(
                    f"row {i}: amount '{raw_amount}' is not a number"
                )
            transactions.append(
                {"date": parsed_date.isoformat(), "description": raw_desc, "amount": amount}
            )

    if not transactions:
        raise BoundaryValidationError("no transactions found in CSV")

    as_of = max(t["date"] for t in transactions)
    log(f"ingested {len(transactions)} transactions through {as_of}")
    return {"as_of": as_of, "transactions": transactions}


if __name__ == "__main__":
    run("ingest", handler)
