import os
import unittest


class TestEnvIsolationTests(unittest.TestCase):
    def test_test_env_forces_mock_model(self) -> None:
        self.assertEqual(os.environ.get("OPENAI_MODEL"), "mock")
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        self.assertNotIn("OPENAI_BASE_URL", os.environ)


if __name__ == "__main__":
    unittest.main()
