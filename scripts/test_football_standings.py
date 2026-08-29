#!/usr/bin/env python3
"""Tests for goalsFor/goalsAgainst in football factual standings."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from snapshot_standings import parse_standings_payload

SOCCER_LEAGUE_IDS = [
    league_id
    for league_id, source in json.loads((_SCRIPTS_DIR / "sources.json").read_text(encoding="utf-8")).items()
    if str(source.get("path", "")).startswith("soccer/")
]


def _standings_rows(payload: dict) -> list[dict]:
    if "rows" in payload:
        return payload["rows"]
    if "standings" in payload:
        return payload["standings"]
    return []


def _latest_paths(league_id: str) -> list[Path]:
    paths: list[Path] = []
    contests_latest = _ROOT / "data" / "contests" / league_id / "facts" / "latest.json"
    history_latest = _ROOT / "data" / "history" / league_id / "latest.json"
    if contests_latest.is_file():
        paths.append(contests_latest)
    if history_latest.is_file():
        paths.append(history_latest)
    return paths


class ParseSoccerStandingsTests(unittest.TestCase):
    def test_espn_points_for_against_mapped_to_goals(self) -> None:
        payload = {
            "season": {"year": 2026},
            "children": [
                {
                    "name": "2026-27 Russian Premier League",
                    "standings": {
                        "season": 2026,
                        "entries": [
                            {
                                "team": {"displayName": "Krasnodar"},
                                "stats": [
                                    {"name": "wins", "value": 4},
                                    {"name": "ties", "value": 0},
                                    {"name": "losses", "value": 0},
                                    {"name": "gamesPlayed", "value": 4},
                                    {"name": "points", "value": 12},
                                    {"name": "pointsFor", "value": 9},
                                    {"name": "pointsAgainst", "value": 4},
                                    {"name": "pointDifferential", "value": 5},
                                    {"name": "rank", "value": 1},
                                ],
                            }
                        ],
                    },
                }
            ],
        }

        rows, season_year = parse_standings_payload(payload)

        self.assertEqual(season_year, 2026)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["team"], "Krasnodar")
        self.assertEqual(row["goalsFor"], 9)
        self.assertEqual(row["goalsAgainst"], 4)
        self.assertEqual(row["goalDifference"], 5)
        self.assertEqual(row["points"], 12)


class FootballSnapshotSchemaTests(unittest.TestCase):
    def test_soccer_latest_snapshots_include_gf_ga(self) -> None:
        checked: list[str] = []
        for league_id in SOCCER_LEAGUE_IDS:
            paths = _latest_paths(league_id)
            if not paths:
                continue
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = _standings_rows(payload)
                self.assertTrue(rows, f"{path}: empty standings")
                for row in rows:
                    self.assertIn(
                        "goalsFor",
                        row,
                        f"{path}: row {row.get('participantId') or row.get('team')} missing goalsFor",
                    )
                    self.assertIn(
                        "goalsAgainst",
                        row,
                        f"{path}: row {row.get('participantId') or row.get('team')} missing goalsAgainst",
                    )
                    self.assertIsInstance(row["goalsFor"], int)
                    self.assertIsInstance(row["goalsAgainst"], int)
                checked.append(str(path.relative_to(_ROOT)))

        self.assertTrue(checked, "expected at least one soccer latest.json snapshot on disk")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
