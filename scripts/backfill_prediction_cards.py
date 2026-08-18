#!/usr/bin/env python3
"""Backfill predictions/card.json from existing latest.json snapshots."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import (
    CONTESTS_DIR,
    predictions_dir,
    read_json,
    write_contests_index,
    write_prediction_card,
)


def list_contest_ids() -> list[str]:
    if not CONTESTS_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in CONTESTS_DIR.iterdir()
        if path.is_dir() and (path / "contest.json").exists()
    )


def backfill_contest(contest_id: str, *, dry_run: bool = False) -> bool:
    latest_path = predictions_dir(contest_id) / "latest.json"
    if not latest_path.exists():
        print(f"skip {contest_id}: no predictions/latest.json")
        return False

    latest = read_json(latest_path)
    items = latest.get("items") or []
    if not items:
        print(f"skip {contest_id}: empty items")
        return False

    if dry_run:
        print(f"dry-run {contest_id}: {len(items)} items")
        return True

    out = write_prediction_card(contest_id, latest, items)
    print(f"ok {contest_id}: {len(items)} items -> {out}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contest", help="Single contest id (default: all from manifest)")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contest_ids = [args.contest] if args.contest else list_contest_ids()
    if not contest_ids:
        print("No contests found", file=sys.stderr)
        return 2

    written = 0
    for contest_id in contest_ids:
        if backfill_contest(contest_id, dry_run=args.dry_run):
            written += 1

    if not args.dry_run and written:
        write_contests_index()

    print(f"done: {written}/{len(contest_ids)} contests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
