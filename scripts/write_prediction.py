#!/usr/bin/env python3
"""Write a predictions snapshot into data/contests/{contestId}/predictions/."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import (
    contest_dir,
    list_standings_days,
    resolve_or_create_participant,
    utc_now_iso,
    write_prediction_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contest", required=True, help="Contest id, e.g. rpl-26-27")
    parser.add_argument(
        "--input",
        required=True,
        help="JSON file: [{team|participantId, probability|win_predict}, ...]",
    )
    parser.add_argument("--date", help="Snapshot date YYYY-MM-DD (default: facts last or today UTC)")
    parser.add_argument("--based-on-facts-date", help="Override basedOnFactsDate")
    parser.add_argument("--model-name", default="cursor-cloud")
    parser.add_argument("--model-version", default="composer-2.5")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_items(contest_id: str, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in raw:
        participant_id = row.get("participantId") or row.get("entrantId")
        if not participant_id:
            team = row.get("team")
            if not team:
                raise SystemExit(f"item missing participantId/team: {row}")
            participant_id, _ = resolve_or_create_participant(contest_id, str(team))
        probability = row.get("probability", row.get("win_predict"))
        if probability is None:
            raise SystemExit(f"item missing probability: {row}")
        items.append({"participantId": participant_id, "probability": float(probability)})
    return items


def main() -> int:
    args = parse_args()
    contest_id = args.contest
    if not (contest_dir(contest_id) / "contest.json").exists():
        print(f"Unknown contest: {contest_id}", file=sys.stderr)
        return 2

    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("Input must be a JSON array", file=sys.stderr)
        return 2

    items = normalize_items(contest_id, raw)
    facts_days = list_standings_days(contest_id)
    based_on = args.based_on_facts_date or (facts_days[-1] if facts_days else None)
    snapshot_date = args.date or based_on or utc_now_iso()[:10]

    if args.dry_run:
        print(
            f"dry-run {contest_id}@{snapshot_date}: {len(items)} items "
            f"basedOnFactsDate={based_on}"
        )
        return 0

    out = write_prediction_snapshot(
        contest_id,
        snapshot_date=snapshot_date,
        generated_at=utc_now_iso(),
        model={"name": args.model_name, "version": args.model_version},
        based_on_facts_date=based_on,
        items=items,
    )
    print(f"ok {contest_id}@{snapshot_date}: {len(items)} items -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
