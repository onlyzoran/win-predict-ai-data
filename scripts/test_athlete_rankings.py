#!/usr/bin/env python3
"""Tests for athlete-based ESPN rankings (tennis, MMA)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from snapshot_standings import fetch_espn_rankings


class AthleteRankingsTests(unittest.TestCase):
    def test_tennis_atp_returns_named_players(self) -> None:
        rows, _ = fetch_espn_rankings("tennis/atp", "atp")
        self.assertGreaterEqual(len(rows), 10)
        self.assertNotEqual(rows[0]["team"], "Unknown")
        self.assertEqual(rows[0]["rank"], 1)

    def test_mma_ufc_pound_for_pound_returns_named_fighters(self) -> None:
        rows, _ = fetch_espn_rankings("mma/ufc", "pound")
        self.assertGreaterEqual(len(rows), 5)
        self.assertNotEqual(rows[0]["team"], "Unknown")
        self.assertEqual(rows[0]["rank"], 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
