#!/usr/bin/env python
"""Benchmark the core pipeline: classify -> validate -> aggregate.

This measures the domain engine in isolation (no DB, no HTTP, no file
I/O) at increasing batch sizes, so the number reported is specifically
"how fast is the business logic", independent of infrastructure. Results
observed on the author's development machine are recorded in the
README's Benchmark section — re-run this yourself to get numbers for
your own hardware.

Usage:
    python scripts/benchmark.py --sizes 1000 10000 50000
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.models.transaction import Transaction
from app.domain.rules.registry import RULE_SET_V1
from app.domain.services.report_builder import build_report


def _build_transactions(count: int, seed: int = 42) -> list[Transaction]:
    random.seed(seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hints = [None, None, None, "wire", "internal_transfer", "fee", "refund"]
    transactions = []
    for i in range(count):
        transactions.append(
            Transaction(
                external_id=f"BENCH-{i:08d}",
                timestamp=start + timedelta(seconds=random.randint(0, 60 * 60 * 24 * 30)),
                amount=Decimal(str(round(random.uniform(1, 25000), 2))),
                currency="USD",
                counterparty=f"Counterparty {i % 500}",
                raw_category_hint=random.choice(hints),
            )
        )
    return transactions


def run_benchmark(sizes: list[int]) -> None:
    print(f"{'Transactions':>14} | {'Time (s)':>10} | {'Tx/sec':>12}")
    print("-" * 42)
    for size in sizes:
        transactions = _build_transactions(size)
        start_time = time.perf_counter()
        result = build_report(
            transactions=transactions,
            rule_set=RULE_SET_V1,
            period_start=datetime(2026, 1, 1, tzinfo=UTC).date(),
            period_end=datetime(2026, 1, 31, tzinfo=UTC).date(),
        )
        elapsed = time.perf_counter() - start_time
        throughput = size / elapsed if elapsed > 0 else float("inf")
        print(f"{size:>14,} | {elapsed:>10.3f} | {throughput:>12,.0f}")
        assert result.input_transaction_count == size  # sanity check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1_000, 10_000, 50_000, 100_000])
    args = parser.parse_args(argv)
    run_benchmark(args.sizes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
