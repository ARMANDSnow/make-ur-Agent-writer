"""iter067 F3: write_json must refuse to persist non-finite floats.

The default json.dumps has allow_nan=True, emitting bare NaN/Infinity tokens —
invalid JSON that read_json's json.loads happily re-parses. That let a corrupt
entity_graph.json round-trip back to disk on confirm, and would let a NaN budget
land in driver_state.json. write_json now passes allow_nan=False, so a non-finite
payload raises ValueError before any file is written (no partial/tmp artifact).

Mock-only; tmpdir-isolated, no real workspace data.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.utils import read_json, write_json


class WriteJsonFiniteGuardTests(unittest.TestCase):
    def test_nan_value_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            with self.assertRaises(ValueError):
                write_json(path, {"confidence": float("nan")})

    def test_infinity_value_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            for bad in (float("inf"), float("-inf")):
                with self.assertRaises(ValueError):
                    write_json(path, {"x": bad})

    def test_nested_non_finite_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            payload = {"a": [{"b": [1.0, float("nan")]}]}
            with self.assertRaises(ValueError):
                write_json(path, payload)

    def test_rejected_payload_leaves_no_file_or_tmp(self) -> None:
        # Serialize-before-touch: a rejected write must not create the target
        # file nor leave a .tmp.* artifact behind.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "out.json"
            with self.assertRaises(ValueError):
                write_json(path, {"x": float("nan")})
            self.assertFalse(path.exists())
            leftovers = [p.name for p in root.iterdir()]
            self.assertEqual(leftovers, [], leftovers)

    def test_finite_payload_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            data = {"confidence": 0.85, "name": "中文", "list": [1, 2, 3]}
            write_json(path, data)
            self.assertEqual(read_json(path), data)


if __name__ == "__main__":
    unittest.main()
