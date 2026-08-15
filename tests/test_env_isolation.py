import os
import unittest


class TestEnvIsolationTests(unittest.TestCase):
    def test_novel_test_environment_is_mock_and_offline(self) -> None:
        self.assertEqual(os.environ.get("OPENAI_MODEL"), "mock")
        self.assertEqual(os.environ.get("PLANNER_MODEL"), "mock")
        self.assertEqual(os.environ.get("DRAGON_RAJA_SKIP_DOTENV"), "1")
        self.assertNotIn("OPENAI_API_KEY", os.environ)


if __name__ == "__main__":
    unittest.main()
