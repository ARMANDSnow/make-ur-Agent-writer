import unittest

from src.web.routes import _validate_write_book_params


class RoutesWriteBookTierTests(unittest.TestCase):
    def test_invalid_tier_returns_error(self) -> None:
        error, params = _validate_write_book_params({"chapters": 1, "tier": "strict"})
        self.assertIsNotNone(error)
        self.assertEqual(params, {})
        self.assertIn("WRITE_REVIEW_TIER", error or "")

    def test_missing_tier_defaults_to_mid(self) -> None:
        error, params = _validate_write_book_params({"chapters": 1})
        self.assertIsNone(error)
        self.assertEqual(params["tier"], "mid")


if __name__ == "__main__":
    unittest.main()
