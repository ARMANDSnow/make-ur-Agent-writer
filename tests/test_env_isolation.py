import os
import unittest


class TestEnvIsolationTests(unittest.TestCase):
    def test_test_env_forces_mock_model(self) -> None:
        self.assertEqual(os.environ.get("OPENAI_MODEL"), "mock")
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        self.assertNotIn("OPENAI_BASE_URL", os.environ)
        self.assertNotIn("PLANNER_API_KEY", os.environ)
        self.assertNotIn("PLANNER_BASE_URL", os.environ)
        self.assertNotIn("PLANNER_MODEL", os.environ)
        self.assertNotIn("AI_DRAW_ENDPOINT", os.environ)
        self.assertNotIn("AI_DRAW_BASE_URL", os.environ)
        self.assertNotIn("AI_DRAW_MODEL", os.environ)
        self.assertNotIn("AI_DRAW_API_KEY", os.environ)
        self.assertNotIn("AI_DRAW_RESULT_HOSTS", os.environ)
        self.assertNotIn("SD_API_BASE_URL", os.environ)
        self.assertNotIn("SD_API_KEY", os.environ)
        self.assertNotIn("OPENAI_STREAM", os.environ)


if __name__ == "__main__":
    unittest.main()
