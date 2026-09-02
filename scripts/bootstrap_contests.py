#!/usr/bin/env python3
"""Add new competitions from scripts/new_competitions.json into the catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import write_contests_index, write_json

ROOT = _SCRIPTS_DIR.parent
LEAGUES_PATH = ROOT / "data" / "leagues.json"
SOURCES_PATH = _SCRIPTS_DIR / "sources.json"
NEW_COMPETITIONS_PATH = _SCRIPTS_DIR / "new_competitions.json"
CONTESTS_DIR = ROOT / "data" / "contests"


def league_entry(comp: dict[str, Any]) -> dict[str, Any]:
    contest_id = comp["id"]
    return {
        "id": contest_id,
        "title": comp["title"],
        "fullTitle": comp["fullTitle"],
        "sport": comp["sport"],
        "startDate": comp["startDate"],
        "endDate": comp["endDate"],
        "endDateTo": comp.get("endDateTo", ""),
        "popularPriority": comp["popularPriority"],
        "layout": "contests",
        "contestPath": f"contests/{contest_id}",
    }


def contest_payload(comp: dict[str, Any]) -> dict[str, Any]:
    source = comp.get("source") or {}
    has_facts = comp.get("hasFacts")
    if has_facts is None:
        has_facts = bool(source and source.get("provider") not in (None, "unsupported"))

    category = "politics" if comp["sport"] == "politics" else "sport"
    payload: dict[str, Any] = {
        "id": comp["id"],
        "title": comp["title"],
        "fullTitle": comp["fullTitle"],
        "category": category,
        "sport": comp["sport"],
        "target": "champion",
        "season": {"start": comp["startDate"], "end": comp["endDate"]},
        "hasFacts": has_facts,
        "predictionTarget": "win_probability",
    }
    if has_facts:
        payload["metric"] = source.get("metric") or "points"
        payload["factKinds"] = ["standings" if source.get("kind") == "standings" else "rankings"]
        payload["factsGrain"] = comp.get("factsGrain") or "day"
    return payload


def bootstrap_one(comp: dict[str, Any], *, force: bool) -> None:
    contest_id = comp["id"]
    contest_root = CONTESTS_DIR / contest_id
    if contest_root.exists() and not force:
        raise SystemExit(f"{contest_id}: contest dir already exists (use --force to overwrite skeleton)")

    write_json(contest_root / "contest.json", contest_payload(comp))
    write_json(
        contest_root / "participants.json",
        {"contestId": contest_id, "participants": []},
    )
    write_json(
        contest_root / "predictions" / "index.json",
        {
            "contestId": contest_id,
            "kind": "predictions",
            "count": 0,
            "first": None,
            "last": None,
            "days": [],
        },
    )


def merge_catalog(new_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    existing_ids = {entry["id"] for entry in leagues}

    for comp in new_items:
        contest_id = comp["id"]
        if contest_id in existing_ids:
            raise SystemExit(f"{contest_id}: already present in leagues.json")
        leagues.append(league_entry(comp))
        source = comp.get("source")
        if source:
            sources[contest_id] = source
        existing_ids.add(contest_id)

    leagues.sort(key=lambda entry: (entry.get("popularPriority") or 0, entry["id"]))
    return leagues, sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=NEW_COMPETITIONS_PATH,
        help="JSON file with new competition definitions.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print summary without writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing contest skeleton directories.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    new_items = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(new_items, list) or not new_items:
        raise SystemExit("input must be a non-empty JSON array")

    current_count = len(json.loads(LEAGUES_PATH.read_text(encoding="utf-8")))
    expected_total = 50
    if current_count + len(new_items) != expected_total:
        raise SystemExit(
            f"catalog size mismatch: current={current_count} + new={len(new_items)} != {expected_total}"
        )

    leagues, sources = merge_catalog(new_items)

    if args.dry_run:
        print(f"dry-run: would add {len(new_items)} competitions -> total {len(leagues)}")
        for comp in new_items:
            print(f"  - {comp['id']} ({comp['sport']})")
        return 0

    for comp in new_items:
        bootstrap_one(comp, force=args.force)

    write_json(LEAGUES_PATH, leagues)
    write_json(SOURCES_PATH, sources)
    write_contests_index()

    print(f"leagues.json: {len(leagues)} entries")
    print(f"sources.json: {len(sources)} entries")
    print(f"contests index rebuilt -> {CONTESTS_DIR / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
