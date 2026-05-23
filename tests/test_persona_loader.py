"""Iter 016: persona_loader regression tests.

Covers:
* load_personas returns None when file missing or protagonist empty (legacy
  fallback path stays alive).
* render_agent_fields returns rendered templates when personas present, and
  legacy values when personas missing.
* Undefined template variables collapse to empty string rather than raising,
  so a partial persona file does not break debate/review.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.persona_loader import (
    load_personas,
    render_agent_fields,
    render_template,
)


class PersonaLoaderTests(unittest.TestCase):
    def test_load_personas_returns_none_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertIsNone(load_personas(path))

    def test_load_personas_returns_none_when_protagonist_blank(self) -> None:
        """An applied file with empty protagonist_name should still trigger
        the legacy fallback path — rendering ``"{protagonist_name}本位"`` to
        just ``"本位"`` would obviously break agent identity.
        """

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "personas.json"
            path.write_text(json.dumps({"protagonist_name": ""}), encoding="utf-8")
            self.assertIsNone(load_personas(path))

    def test_load_personas_returns_dict_when_protagonist_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "personas.json"
            path.write_text(
                json.dumps(
                    {
                        "protagonist_name": "甲",
                        "protagonist_role": "主角",
                        "author_name": "作者",
                        "style_short_descriptor": "白话",
                        "world_setting_brief": "骨架",
                        "core_relationships": ["甲 与 乙 的 同伴"],
                        "core_setting_rules": ["规则一"],
                    }
                ),
                encoding="utf-8",
            )
            data = load_personas(path)
        self.assertIsNotNone(data)
        assert data is not None  # for mypy/type narrowing
        self.assertEqual(data["protagonist_name"], "甲")

    def test_render_template_substitutes_known_vars(self) -> None:
        personas = {
            "protagonist_name": "甲",
            "author_name": "作者",
            "core_setting_rules": ["规则一", "规则二"],
        }
        rendered = render_template(
            "你代表{protagonist_name}本位（作者：{author_name}）。规则：{core_setting_rules_text}",
            personas,
        )
        self.assertIn("甲本位", rendered)
        self.assertIn("作者：作者", rendered)
        # list field rendered as bullet text by _personas_context.
        self.assertIn("- 规则一", rendered)
        self.assertIn("- 规则二", rendered)

    def test_render_template_handles_unknown_vars_as_empty(self) -> None:
        rendered = render_template("a={unknown}|b={protagonist_name}", {"protagonist_name": "甲"})
        self.assertEqual(rendered, "a=|b=甲")

    def test_render_agent_fields_uses_legacy_when_personas_none(self) -> None:
        agent = {
            "name": "legacy_name",
            "system_prompt": "legacy prompt",
            "stance": "legacy stance",
            "name_template": "{protagonist_name}本位",
            "system_prompt_template": "你代表{protagonist_name}",
            "stance_template": "新模板",
        }
        name, prompt, stance = render_agent_fields(agent, None)
        self.assertEqual(name, "legacy_name")
        self.assertEqual(prompt, "legacy prompt")
        self.assertEqual(stance, "legacy stance")

    def test_render_agent_fields_uses_template_when_personas_present(self) -> None:
        agent = {
            "name": "路明非本位",
            "system_prompt": "legacy prompt with 路明非",
            "stance": "legacy stance with 路明非",
            "name_template": "{protagonist_name}本位",
            "system_prompt_template": "你代表{protagonist_name}本位（{protagonist_role}）。",
            "stance_template": "{protagonist_name} 的选择必须有意义。",
        }
        personas = {"protagonist_name": "甲", "protagonist_role": "主角"}
        name, prompt, stance = render_agent_fields(agent, personas)
        self.assertEqual(name, "甲本位")
        self.assertEqual(prompt, "你代表甲本位（主角）。")
        self.assertEqual(stance, "甲 的选择必须有意义。")
        # Legacy substring must be replaced — no leak from validation corpus.
        self.assertNotIn("路明非", name)
        self.assertNotIn("路明非", prompt)
        self.assertNotIn("路明非", stance)

    def test_render_agent_fields_falls_back_per_field_when_template_missing(self) -> None:
        agent = {
            "name": "legacy_name",
            "system_prompt": "legacy prompt",
            # only template name; no system_prompt_template.
            "name_template": "{protagonist_name}本位",
        }
        personas = {"protagonist_name": "甲"}
        name, prompt, _ = render_agent_fields(agent, personas)
        self.assertEqual(name, "甲本位")
        # No template for system_prompt → fall back to legacy.
        self.assertEqual(prompt, "legacy prompt")


if __name__ == "__main__":
    unittest.main()
