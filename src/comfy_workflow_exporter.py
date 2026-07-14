"""Build versioned, local-only ComfyUI workflow templates for drama episodes.

The generated document is deliberately a template: checkpoint and LoRA file
names are placeholders that the operator must map to models installed in their
own ComfyUI environment.  Building it performs no network or filesystem I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .drama_schemas import CharacterSheet, DramaEpisode, normalize_episode_no


GENERATOR_VERSION = "drama_comfy_exporter_v1"
TEMPLATE_NOTICE = "模板级导出：导入后仍需按本地模型与 workflow 接线。"

_NEGATIVE_PROMPT = (
    "low quality, blurry, deformed hands, extra fingers, duplicate person, "
    "watermark, text, logo"
)


def build_workflow(
    episode: Dict[str, Any], characters: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a deterministic ComfyUI API-workflow template for every shot."""

    episode_no = normalize_episode_no(episode.get("episode_no"))
    episode_model = DramaEpisode(**episode)
    if episode_model.episode_no != episode_no:
        raise ValueError("episode_no normalization mismatch")
    character_sheet = CharacterSheet(**characters)
    active_characters = [
        character
        for character in character_sheet.characters
        if episode_model.episode_no in character.appearances
    ]
    if not active_characters:
        raise ValueError("episode character projection is empty")
    if len(active_characters) > 8:
        raise ValueError("an episode may include at most 8 characters")

    workflow: Dict[str, Any] = {
        "_generator": GENERATOR_VERSION,
        "_notice": TEMPLATE_NOTICE,
    }
    next_node_id = 1

    def add_node(class_type: str, inputs: Dict[str, Any], title: str) -> str:
        nonlocal next_node_id
        node_id = str(next_node_id)
        next_node_id += 1
        workflow[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": title},
        }
        return node_id

    seen_shot_numbers = set()
    for raw_shot in episode_model.storyboard:
        if not isinstance(raw_shot, dict):
            raise ValueError("episode storyboard rows must be objects")
        shot_no = _positive_shot_no(raw_shot.get("shot_no"))
        if shot_no in seen_shot_numbers:
            raise ValueError("episode storyboard shot numbers must be unique")
        seen_shot_numbers.add(shot_no)
        prefix = f"episode_{episode_model.episode_no:02d}_shot_{shot_no:02d}"

        checkpoint_id = add_node(
            "CheckpointLoaderSimple",
            {"ckpt_name": "<select-local-checkpoint>.safetensors"},
            f"{prefix} checkpoint",
        )
        model_ref: List[Any] = [checkpoint_id, 0]
        clip_ref: List[Any] = [checkpoint_id, 1]
        vae_ref: List[Any] = [checkpoint_id, 2]

        for character in active_characters:
            lora_id = add_node(
                "LoraLoader",
                {
                    "model": model_ref,
                    "clip": clip_ref,
                    "lora_name": f"{character.lora_token}.safetensors",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                },
                f"{prefix} LoRA {character.name}",
            )
            model_ref = [lora_id, 0]
            clip_ref = [lora_id, 1]

        prompt = _positive_prompt(raw_shot, active_characters)
        positive_id = add_node(
            "CLIPTextEncode",
            {"text": prompt, "clip": clip_ref},
            f"{prefix} positive prompt",
        )
        negative_id = add_node(
            "CLIPTextEncode",
            {"text": _NEGATIVE_PROMPT, "clip": clip_ref},
            f"{prefix} negative prompt",
        )
        latent_id = add_node(
            "EmptyLatentImage",
            {"width": 512, "height": 768, "batch_size": 1},
            f"{prefix} latent",
        )
        sampler_id = add_node(
            "KSampler",
            {
                "seed": episode_model.episode_no * 1000 + shot_no,
                "steps": 24,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": model_ref,
                "positive": [positive_id, 0],
                "negative": [negative_id, 0],
                "latent_image": [latent_id, 0],
            },
            f"{prefix} sampler",
        )
        decode_id = add_node(
            "VAEDecode",
            {"samples": [sampler_id, 0], "vae": vae_ref},
            f"{prefix} decode",
        )
        add_node(
            "SaveImage",
            {"filename_prefix": prefix, "images": [decode_id, 0]},
            f"{prefix} save",
        )

    return workflow


def _positive_shot_no(raw: Any) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("shot_no must be a positive integer")
    if raw < 1:
        raise ValueError("shot_no must be a positive integer")
    return raw


def _positive_prompt(raw_shot: Dict[str, Any], characters: List[Any]) -> str:
    parts: List[str] = []
    shot_prompt = raw_shot.get("ai_draw_prompt")
    if isinstance(shot_prompt, str) and shot_prompt.strip():
        parts.append(shot_prompt.strip())
    parts.extend(
        character.prompt_template_sd.strip()
        for character in characters
        if character.prompt_template_sd.strip()
    )
    return ", ".join(parts)
