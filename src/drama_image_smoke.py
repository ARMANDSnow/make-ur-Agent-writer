"""One-image real smoke for the iter089 drama image integration."""

from __future__ import annotations

import json
import os

from . import paths
from .ai_draw_client import DEFAULT_IMAGE_MODEL, redraw_character_reference
from .cli_workspace import init_workspace
from .config import load_dotenv_if_available
from .utils import write_json


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
    if os.getenv("CONFIRM_REAL_IMAGE_SMOKE") != "可以跑生图":
        raise SystemExit("refusing real image smoke without CONFIRM_REAL_IMAGE_SMOKE=可以跑生图")
    load_dotenv_if_available()
    if os.getenv("AI_DRAW_ENDPOINT"):
        raise SystemExit("image smoke requires OpenAI-compatible mode; unset AI_DRAW_ENDPOINT")
    if not (os.getenv("AI_DRAW_BASE_URL") or os.getenv("OPENAI_BASE_URL")):
        raise SystemExit("image smoke requires AI_DRAW_BASE_URL or OPENAI_BASE_URL")
    if not (os.getenv("AI_DRAW_API_KEY") or os.getenv("OPENAI_API_KEY")):
        raise SystemExit("image smoke requires AI_DRAW_API_KEY or OPENAI_API_KEY")
    # Process-local pin only. Never writes .env.
    os.environ["AI_DRAW_MODEL"] = DEFAULT_IMAGE_MODEL
    root = paths.WORKSPACE_DIR / SMOKE_WORKSPACE
    if not root.exists():
        init_workspace(SMOKE_WORKSPACE, type="drama")
    character = build_smoke_character()
    result = redraw_character_reference(SMOKE_WORKSPACE, character, mock=False)
    if not str(result.get("requested_model") or "").startswith(DEFAULT_IMAGE_MODEL):
        raise SystemExit("image smoke did not exercise the gpt-image-2 compatible path")
    output = root / result["path"]
    safe_result = {
        "ok": True,
        "workspace": SMOKE_WORKSPACE,
        "generated_by": result["generated_by"],
        "requested_model": result.get("requested_model", ""),
        "requested_size": result.get("requested_size", ""),
        "provider_size": result.get("provider_size", ""),
        "width": result.get("width"),
        "height": result.get("height"),
        "path": result["path"],
        "bytes": output.stat().st_size,
    }
    metadata_path = output.parent / "smoke_result.json"
    write_json(metadata_path, safe_result)
    print(
        json.dumps(
            {**safe_result, "metadata_path": str(metadata_path.relative_to(root))},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
