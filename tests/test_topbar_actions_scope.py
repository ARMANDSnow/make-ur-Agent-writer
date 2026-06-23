"""iter064 #3: the mobile ``.topbar-actions`` dropdown rule must be scoped to
the shell topbar (``.topbar-actions-wrap``).

The class is reused for both the shell topbar dropdown AND in-page content
action rows (overview "删除作品…", chapter-detail "返回章节列表/回概览"). The
mobile ``@media`` rule sets ``display:none; position:absolute`` (the dropdown
pattern), so a bare ``.topbar-actions`` selector hid the content buttons at
<=768px. Pin the scoped selector so it can't regress.

Mock-only; pure string assertions on the CSS bundle.
"""

from __future__ import annotations

import re
import unittest

from src.web import static


class TopbarActionsMobileScopeTests(unittest.TestCase):
    def test_mobile_dropdown_rule_scoped_to_shell(self) -> None:
        css = static.CSS_BODY
        self.assertIn(".topbar-actions-wrap .topbar-actions {", css)
        # Regression guard: a bare ".topbar-actions {" immediately followed by
        # "display: none" inside the media query would re-hide content buttons.
        self.assertNotRegex(
            css, r"(?m)^\s*\.topbar-actions\s*\{\s*\n\s*display:\s*none"
        )

    def test_open_and_btn_rules_also_scoped(self) -> None:
        css = static.CSS_BODY
        self.assertIn(".topbar-actions-wrap .topbar-actions.open", css)
        self.assertIn(".topbar-actions-wrap .topbar-actions .btn", css)


if __name__ == "__main__":
    unittest.main()
