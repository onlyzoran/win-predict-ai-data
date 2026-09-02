#!/usr/bin/env python3
"""Seed predictions/latest.json and card.json from facts or uniform off-season priors."""

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
    CONTESTS_DIR,
    contest_dir,
    load_contest,
    load_participants,
    predictions_dir,
    read_json,
    save_participants,
    utc_now_iso,
    write_contests_index,
    write_json,
    write_prediction_card,
    write_prediction_snapshot,
)

ROOT = _SCRIPTS_DIR.parent
LEAGUES_PATH = ROOT / "data" / "leagues.json"
SOURCES_PATH = _SCRIPTS_DIR / "sources.json"

GRAND_SLAM_CONTESTS = frozenset(
    {
        "tennis-australian-open-27",
        "tennis-french-open-27",
        "tennis-wimbledon-27",
        "tennis-us-open-27",
    }
)
GRAND_SLAM_TOP_N = 32
SEED_MODEL = {"name": "standings-heuristic", "version": "seed-v1"}
UNIFORM_MODEL = {"name": "uniform-prior", "version": "off-season-v1"}


def load_sources() -> dict[str, Any]:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def load_league_ids() -> list[str]:
    leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
    return [entry["id"] for entry in leagues]


def metric_for(contest_id: str) -> str:
    source = load_sources().get(contest_id) or {}
    if source.get("metric"):
        return str(source["metric"])
    contest = load_contest(contest_id)
    return str(contest.get("metric") or "points")


def row_score(row: dict[str, Any], metric: str, *, all_points_zero: bool) -> float:
    rank = row.get("rank") or row.get("sourceRank") or 999
    if metric == "rank":
        points = row.get("points")
        if points is not None and float(points) > 0:
            return float(points)
        return float(max(1, 201 - int(rank)))

    if metric == "wins":
        win_percent = row.get("winPercent")
        wins = row.get("wins")
        if win_percent is not None and float(win_percent) > 0:
            return float(win_percent) * 100.0
        if wins is not None and int(wins) > 0:
            return float(wins)
        return float(max(1, 201 - int(rank)))

    points = row.get("points")
    if points is not None and float(points) > 0:
        goal_diff = row.get("goalDifference") or 0
        return float(points) * 1000.0 + float(goal_diff)

    if all_points_zero:
        return float(max(1, 201 - int(rank)))

    played = row.get("played") or row.get("wins") or 0
    goal_diff = row.get("goalDifference") or 0
    return float(played) * 10.0 + float(goal_diff) + float(max(1, 201 - int(rank)))


def normalize_probabilities(items: list[tuple[str, float]]) -> list[dict[str, Any]]:
    if not items:
        return []

    total = sum(score for _, score in items)
    if total <= 0:
        uniform = 100.0 / len(items)
        rounded = [round(uniform, 2) for _ in items]
    else:
        raw = [(pid, score / total * 100.0) for pid, score in items]
        rounded = [round(prob, 2) for _, prob in raw]

    delta = round(100.0 - sum(rounded), 2)
    if rounded:
        rounded[0] = round(rounded[0] + delta, 2)

    return [{"participantId": pid, "probability": prob} for (pid, _), prob in zip(items, rounded)]


def uniform_items(participant_ids: list[str]) -> list[dict[str, Any]]:
    if not participant_ids:
        return []
    pairs = [(pid, 1.0) for pid in participant_ids]
    return normalize_probabilities(pairs)


def items_from_facts(contest_id: str, facts: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    rows = facts.get("rows") or []
    if not rows:
        return []

    points_values = [row.get("points") for row in rows if row.get("points") is not None]
    all_points_zero = bool(points_values) and all(float(value) == 0 for value in points_values)

    scored = [
        (str(row["participantId"]), row_score(row, metric, all_points_zero=all_points_zero))
        for row in rows
        if row.get("participantId")
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return normalize_probabilities(scored)


def seed_grand_slam_participants(contest_id: str) -> int:
    """Copy top ATP/WTA ranked players into a Grand Slam participant list."""
    selected: dict[str, dict[str, Any]] = {}

    for source_contest in ("tennis-atp-26", "tennis-wta-26"):
        facts_path = contest_dir(source_contest) / "facts" / "latest.json"
        if not facts_path.exists():
            continue
        facts = read_json(facts_path)
        ranked_rows = sorted(
            (row for row in facts.get("rows") or [] if row.get("participantId")),
            key=lambda row: row.get("rank") or 999,
        )[:GRAND_SLAM_TOP_N]

        participants = {
            item["id"]: item for item in load_participants(source_contest).get("participants") or []
        }
        for row in ranked_rows:
            participant = participants.get(row["participantId"])
            if participant:
                selected[participant["id"]] = participant

    payload = {"contestId": contest_id, "participants": sorted(selected.values(), key=lambda p: p["name"].casefold())}
    save_participants(contest_id, payload)
    return len(payload["participants"])


def seed_contest(contest_id: str, *, dry_run: bool = False, force: bool = False) -> str:
    card_path = predictions_dir(contest_id) / "card.json"
    latest_path = predictions_dir(contest_id) / "latest.json"

    if card_path.exists() and not force:
        card = read_json(card_path)
        if card.get("items"):
            return f"skip {contest_id}: card.json already populated"

    if latest_path.exists() and not card_path.exists() and not force:
        if dry_run:
            return f"dry-run {contest_id}: would backfill card from latest.json"
        latest = read_json(latest_path)
        items = latest.get("items") or []
        if not items:
            return f"skip {contest_id}: latest.json has empty items"
        write_prediction_card(contest_id, latest, items)
        return f"ok {contest_id}: backfilled card from latest.json ({len(items)} items)"

    if contest_id in GRAND_SLAM_CONTESTS:
        participants = load_participants(contest_id).get("participants") or []
        if not participants:
            if dry_run:
                return f"dry-run {contest_id}: would seed grand-slam participants + uniform predictions"
            added = seed_grand_slam_participants(contest_id)
            participants = load_participants(contest_id).get("participants") or []
            if not participants:
                return f"skip {contest_id}: failed to seed grand-slam participants (added={added})"

    facts_path = contest_dir(contest_id) / "facts" / "latest.json"
    facts = read_json(facts_path) if facts_path.exists() else None
    metric = metric_for(contest_id)

    if facts and facts.get("rows"):
        items = items_from_facts(contest_id, facts, metric)
        model = SEED_MODEL
        based_on = facts.get("date")
        based_on_tour = facts.get("tour")
        mode = "facts"
    else:
        participant_ids = [
            item["id"] for item in load_participants(contest_id).get("participants") or [] if item.get("id")
        ]
        if not participant_ids:
            return f"skip {contest_id}: no facts and no participants"
        items = uniform_items(participant_ids)
        model = UNIFORM_MODEL
        based_on = None
        based_on_tour = None
        mode = "uniform"

    if not items:
        return f"skip {contest_id}: no prediction items generated"

    snapshot_date = based_on or utc_now_iso()[:10]
    if dry_run:
        return f"dry-run {contest_id}: {mode} -> {len(items)} items"

    write_prediction_snapshot(
        contest_id,
        snapshot_date=snapshot_date,
        generated_at=utc_now_iso(),
        model=model,
        based_on_facts_date=based_on,
        based_on_tour=based_on_tour,
        items=items,
    )
    return f"ok {contest_id}: {mode} -> {len(items)} items"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contest", action="append", help="Contest id (repeatable). Default: all leagues.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing card.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contest_ids = args.contest or load_league_ids()
    if not contest_ids:
        print("No contests found", file=sys.stderr)
        return 2

    statuses: list[str] = []
    for contest_id in contest_ids:
        statuses.append(seed_contest(contest_id, dry_run=args.dry_run, force=args.force))

    for status in statuses:
        print(status)

    if not args.dry_run and any(status.startswith("ok") for status in statuses):
        write_contests_index()
        print(f"contests index rebuilt -> {CONTESTS_DIR / 'index.json'}")

    errors = sum(1 for status in statuses if status.startswith("skip"))
    ok = sum(1 for status in statuses if status.startswith("ok"))
    print(f"done: ok={ok} skip={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
