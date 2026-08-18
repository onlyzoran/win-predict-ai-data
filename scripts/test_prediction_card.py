#!/usr/bin/env python3
"""Unit tests for prediction card generation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from contest_io import (
    PREDICTION_CARD_OTHERS_ID,
    PREDICTION_CARD_TOP_N,
    build_prediction_card_items,
    build_prediction_card_payload,
)


class PredictionCardTests(unittest.TestCase):
    def test_top_five_with_others(self) -> None:
        items = [
            {"participantId": "a", "probability": 40.0},
            {"participantId": "b", "probability": 30.0},
            {"participantId": "c", "probability": 10.0},
            {"participantId": "d", "probability": 8.0},
            {"participantId": "e", "probability": 6.0},
            {"participantId": "f", "probability": 3.0},
            {"participantId": "g", "probability": 2.0},
            {"participantId": "h", "probability": 1.0},
        ]
        names = {"a": "Alpha", "b": "Bravo", "c": "Charlie", "d": "Delta", "e": "Echo", "f": "Foxtrot", "g": "Golf", "h": "Hotel"}

        card_items = build_prediction_card_items(items, names)

        self.assertEqual(len(card_items), PREDICTION_CARD_TOP_N + 1)
        self.assertEqual(card_items[0]["name"], "Alpha")
        self.assertEqual(card_items[-1]["participantId"], PREDICTION_CARD_OTHERS_ID)
        self.assertEqual(card_items[-1]["othersCount"], 3)
        self.assertAlmostEqual(card_items[-1]["probability"], 6.0)

    def test_no_others_when_five_or_fewer(self) -> None:
        items = [
            {"participantId": "a", "probability": 50.0},
            {"participantId": "b", "probability": 30.0},
            {"participantId": "c", "probability": 20.0},
        ]
        names = {"a": "Alpha", "b": "Bravo", "c": "Charlie"}

        card_items = build_prediction_card_items(items, names)

        self.assertEqual(len(card_items), 3)
        self.assertTrue(all(item["participantId"] != PREDICTION_CARD_OTHERS_ID for item in card_items))

    def test_payload_shape(self) -> None:
        snapshot = {
            "date": "2026-08-14",
            "generatedAt": "2026-08-14T08:16:28Z",
            "basedOnFactsDate": "2026-08-11",
            "basedOnTour": 3,
            "target": "champion",
            "unit": "percent",
        }
        items = [{"participantId": "a", "probability": 100.0}]

        payload = build_prediction_card_payload(
            "test-contest",
            snapshot,
            items,
        )

        self.assertEqual(payload["kind"], "predictionCard")
        self.assertEqual(payload["contestId"], "test-contest")
        self.assertEqual(payload["topN"], PREDICTION_CARD_TOP_N)
        self.assertEqual(payload["items"][0]["name"], "a")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
