"""Compatibility blocker for the retired unbudgeted one-image smoke."""

from __future__ import annotations

SMOKE_WORKSPACE = "iter089_image_smoke"


def build_smoke_character() -> dict:
    return {
        "id": "c001",
        "name": "林澈",
        "role": "原创都市短剧主角",
        "age_range": "25-30",
        "gender": "男",
        "lora_token": "lin_che_original",
        "visual_features": {"hair": "黑色短发", "eyes": "沉静坚定"},
        "wardrobe_default": "深灰色风衣与简洁黑色高领",
        "expression_keywords": ["克制", "坚定"],
        "visual_signature": "雨夜霓虹下的深灰风衣青年",
        "prompt_template_sd": (
            "原创现代都市短剧角色，二十八岁东亚男性，黑色短发，深灰风衣，"
            "雨夜霓虹电影光，高质感写实人像，半身正面，干净背景，无文字，无标志"
        ),
        "reference_images": [],
        "appearances": [1],
        "manual_override": False,
        "visual_contrast_with": {},
        "agent_suggestions": [],
    }


def main() -> int:
    raise SystemExit(
        "legacy drama_image_smoke is disabled; use drama_multimodal_smoke "
        "for budgeted all-character image testing"
    )


if __name__ == "__main__":
    raise SystemExit(main())
