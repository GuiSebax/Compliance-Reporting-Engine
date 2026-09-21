#!/usr/bin/env python
"""Generate a synthetic batch of transactions for demos, load testing, and
the benchmark script.

Usage:
    python scripts/generate_synthetic_dataset.py --count 10000 --format csv \
        --output sample_data/synthetic_10k.csv

A small fraction of rows are deliberately generated as either malformed
(so ``/batches/upload`` has something real to reject) or as business-rule
violations (so a triggered report has real violations/HIGH_VALUE line
items to show), configurable via ``--invalid-rate`` /
``--violation-rate``. Everything is seeded (``--seed``) for reproducible
demo datasets.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from faker import Faker

_HINTS = [None, None, None, "wire", "internal_transfer", "fee", "refund"]


def _random_timestamp(fake: Faker, start: datetime, end: datetime) -> datetime:
    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, max(delta_seconds, 1)))


def generate_rows(
    *,
    count: int,
    start: datetime,
    end: datetime,
    invalid_rate: float,
    violation_rate: float,
    seed: int,
) -> list[dict]:
    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    rows: list[dict] = []
    for i in range(count):
        roll = random.random()
        external_id = f"SYN-{i:07d}"
        timestamp = _random_timestamp(fake, start, end)
        hint = random.choice(_HINTS)

        if roll < invalid_rate:
            # Syntactically malformed on purpose (missing amount) — exercises
            # ingestion's row-level rejection path.
            rows.append(
                {
                    "external_id": external_id,
                    "timestamp": timestamp.isoformat(),
                    "amount": "not-a-number",
                    "currency": "USD",
                    "counterparty": fake.company(),
                    "raw_category_hint": hint or "",
                }
            )
            continue

        if roll < invalid_rate + violation_rate:
            # Syntactically valid, business-invalid: high value with no
            # counterparty (CRITICAL) or a malformed (non-3-letter)
            # currency code caught by CurrencyFormatRule.
            if random.random() < 0.5:
                amount = str(Decimal("10000.00") + Decimal(random.randint(1, 50000)))
                rows.append(
                    {
                        "external_id": external_id,
                        "timestamp": timestamp.isoformat(),
                        "amount": amount,
                        "currency": "USD",
                        "counterparty": "",
                        "raw_category_hint": "",
                    }
                )
            else:
                rows.append(
                    {
                        "external_id": external_id,
                        "timestamp": timestamp.isoformat(),
                        "amount": str(round(random.uniform(5, 5000), 2)),
                        "currency": random.choice(["US", "usd", "12A"]),
                        "counterparty": fake.company(),
                        "raw_category_hint": "",
                    }
                )
            continue

        amount = round(random.uniform(1, 25000), 2)
        rows.append(
            {
                "external_id": external_id,
                "timestamp": timestamp.isoformat(),
                "amount": str(amount),
                "currency": "USD",
                "counterparty": fake.company(),
                "raw_category_hint": hint or "",
            }
        )

    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "external_id",
                "timestamp",
                "amount",
                "currency",
                "counterparty",
                "raw_category_hint",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict], path: Path) -> None:
    payload = {"transactions": [{k: v for k, v in row.items() if v != ""} for row in rows]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000, help="Number of rows to generate.")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-01-31")
    parser.add_argument(
        "--invalid-rate", type=float, default=0.01, help="Fraction of malformed rows."
    )
    parser.add_argument(
        "--violation-rate", type=float, default=0.03, help="Fraction of business-rule violations."
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    start = datetime.fromisoformat(args.start_date).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end_date).replace(tzinfo=UTC)

    rows = generate_rows(
        count=args.count,
        start=start,
        end=end,
        invalid_rate=args.invalid_rate,
        violation_rate=args.violation_rate,
        seed=args.seed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "csv":
        write_csv(rows, args.output)
    else:
        write_json(rows, args.output)

    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
