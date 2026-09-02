#!/usr/bin/env python3
"""Catalog integrity checks for leagues.json, sources.json, and contests/."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

LEAGUES_PATH = _ROOT / "data" / "leagues.json"
SOURCES_PATH = _SCRIPTS_DIR / "sources.json"
CONTESTS_DIR = _ROOT / "data" / "contests"
INDEX_PATH = CONTESTS_DIR / "index.json"


class CatalogIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.leagues = json.loads(LEAGUES_PATH.read_text(encoding="utf-8"))
        self.sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        self.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    def test_leagues_count_is_fifty(self) -> None:
        self.assertEqual(len(self.leagues), 50)

    def test_league_ids_unique(self) -> None:
        ids = [entry["id"] for entry in self.leagues]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_league_uses_contests_layout(self) -> None:
        for entry in self.leagues:
            self.assertEqual(entry.get("layout"), "contests", entry["id"])
            self.assertEqual(entry.get("contestPath"), f"contests/{entry['id']}", entry["id"])

    def test_contest_skeletons_exist(self) -> None:
        for entry in self.leagues:
            contest_id = entry["id"]
            root = CONTESTS_DIR / contest_id
            self.assertTrue((root / "contest.json").is_file(), contest_id)
            self.assertTrue((root / "participants.json").is_file(), contest_id)
            self.assertTrue((root / "predictions" / "index.json").is_file(), contest_id)

    def test_index_matches_leagues(self) -> None:
        league_ids = {entry["id"] for entry in self.leagues}
        index_ids = set(self.index.get("contests") or {})
        self.assertEqual(league_ids, index_ids)

    def test_espn_sources_have_required_fields(self) -> None:
        for contest_id, source in self.sources.items():
            provider = source.get("provider")
            if provider == "unsupported":
                continue
            if provider == "mlb-statsapi":
                self.assertIn("metric", source, contest_id)
                continue
            self.assertIn("kind", source, contest_id)
            if provider == "espn":
                self.assertIn("path", source, contest_id)
                self.assertIn("metric", source, contest_id)

    def test_every_league_has_prediction_card(self) -> None:
        for entry in self.leagues:
            contest_id = entry["id"]
            card_path = CONTESTS_DIR / contest_id / "predictions" / "card.json"
            self.assertTrue(card_path.is_file(), contest_id)
            card = json.loads(card_path.read_text(encoding="utf-8"))
            self.assertEqual(card.get("kind"), "predictionCard", contest_id)
            self.assertEqual(card.get("contestId"), contest_id, contest_id)
            items = card.get("items") or []
            self.assertTrue(items, f"{contest_id}: card items must not be empty")
            self.assertEqual(items[-1].get("participantId"), "others", contest_id)
            self.assertGreater(items[-1].get("probability", 0), 0, contest_id)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
