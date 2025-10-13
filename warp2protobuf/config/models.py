#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model configuration and catalog for Warp API

Contains model definitions, configurations, and OpenAI compatibility mappings.
"""
import time


def get_model_config(model_name: str) -> dict:
    """
    Simple model configuration mapping.
    All models use the same pattern: base model + o3 planning + auto coding
    """
    # Known models that map directly
    known_models = {
        "claude-4-sonnet",
        "claude-4.5-sonnet",
        "claude-4-opus",
        "claude-4.1-opus",
        "gpt-5",
        "gpt-4o",
        "gpt-4.1",
        "o3",
        "o4-mini",
        "gemini-2.5-pro",
    }

    model_name = model_name.lower().strip()

    # Use the model name directly if it's known, otherwise use "auto"
    base_model = model_name if model_name in known_models else "auto"

    return {
        "base": base_model,
        "planning": "o3",
        "coding": "auto"
    }


def get_warp_models():
    """Get comprehensive list of Warp AI models from packet analysis"""
    return {
        "agent_mode": {
            "default": "gpt-5",
            "models": [
                {
                    "id": "gpt-5",
                    "display_name": "gpt-5",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "claude-4-sonnet",
                    "display_name": "claude-4-sonnet",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "claude-4-5-sonnet",
                    "display_name": "claude-4-5-sonnet",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "claude-4-opus",
                    "display_name": "claude-4-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "claude-4.1-opus",
                    "display_name": "claude-4.1-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "gpt-4o",
                    "display_name": "gpt-4o",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "gpt-4.1",
                    "display_name": "gpt-4.1",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "o4-mini",
                    "display_name": "o4-mini",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "o3",
                    "display_name": "o3",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                },
                {
                    "id": "gemini-2.5-pro",
                    "display_name": "gemini-2.5-pro",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "agent"
                }
            ]
        },
        "planning": {
            "default": "o3",
            "models": [
                {
                    "id": "gpt-5 (high reasoning)",
                    "display_name": "gpt-5 (high reasoning)",
                    "description": None,
                    "vision_supported": False,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "claude-4-opus",
                    "display_name": "claude-4-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "claude-4.1-opus",
                    "display_name": "claude-4.1-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "gpt-4.1",
                    "display_name": "gpt-4.1",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "o4-mini",
                    "display_name": "o4-mini",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "o3",
                    "display_name": "o3",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                }
            ]
        },
        "coding": {
            "default": "auto",
            "models": [
                {
                    "id": "gpt-5",
                    "display_name": "gpt-5",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "claude-4-sonnet",
                    "display_name": "claude-4-sonnet",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "claude-4-opus",
                    "display_name": "claude-4-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "claude-4.1-opus",
                    "display_name": "claude-4.1-opus",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "gpt-4o",
                    "display_name": "gpt-4o",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "gpt-4.1",
                    "display_name": "gpt-4.1",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "o4-mini",
                    "display_name": "o4-mini",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "o3",
                    "display_name": "o3",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "gemini-2.5-pro",
                    "display_name": "gemini-2.5-pro",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                }
            ]
        }
    }


def get_all_unique_models():
    """Get all unique models across all categories for OpenAI API compatibility"""
    try:
        models_data = get_warp_models()
        unique_models = {}

        # Collect all unique models across categories
        for category_data in models_data.values():
            for model in category_data["models"]:
                model_id = model["id"]
                if model_id not in unique_models:
                    # Create OpenAI-compatible model entry
                    unique_models[model_id] = {
                        "id": model_id,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "warp",
                        "display_name": model["display_name"],
                        "description": model["description"],
                        "vision_supported": model["vision_supported"],
                        "usage_multiplier": model["usage_multiplier"],
                        "categories": [model["category"]]
                    }
                else:
                    # Add category if model appears in multiple categories
                    if model["category"] not in unique_models[model_id]["categories"]:
                        unique_models[model_id]["categories"].append(model["category"])

        return list(unique_models.values())

    except Exception:
        # Fallback to simple model list
        return [
            {
                "id": "auto",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "warp",
                "display_name": "auto",
                "description": "Auto-select best model"
            }
        ] 