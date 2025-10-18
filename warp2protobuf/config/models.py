#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model configuration and catalog for Warp API

Contains model definitions, configurations, and OpenAI compatibility mappings.
"""
import time
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import httpx


def get_model_config(model_name: str) -> dict:
    """
    Simple model configuration mapping.
    All models use the same pattern: base model + o3 planning + auto coding
    """
    # Known models that map directly (更新自 Warp GraphQL API 2025-10-18)
    known_models = {
        # Auto 模型
        "auto",
        "auto-efficient",
        
        # GPT-5 系列
        "gpt-5",
        "gpt-5-low-reasoning",
        "gpt-5 (high reasoning)",
        
        # GPT-4 系列
        "gpt-4o",
        "gpt-4.1",
        
        # Claude 4 系列
        "claude-4-sonnet",
        "claude-4-opus",
        "claude-4.1-opus",
        "claude-4-5-haiku",
        "claude-4-5-sonnet",
        "claude-4-5-sonnet-thinking",  # ✅ 新增：支持 thinking 模式
        
        # O系列
        "o3",
        "o4-mini",
        
        # Gemini 系列
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
                    "id": "claude-4-5-haiku",
                    "display_name": "claude-4-5-haiku",
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
                    "id": "claude-4-5-sonnet-thinking",
                    "display_name": "claude-4-5-sonnet-thinking",
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
                    "id": "claude-4-5-sonnet",
                    "display_name": "claude-4-5-sonnet",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "planning"
                },
                {
                    "id": "claude-4-5-sonnet-thinking",
                    "display_name": "claude-4-5-sonnet-thinking",
                    "description": None,
                    "vision_supported": True,
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
                    "id": "claude-4-5-haiku",
                    "display_name": "claude-4-5-haiku",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "claude-4-5-sonnet",
                    "display_name": "claude-4-5-sonnet",
                    "description": None,
                    "vision_supported": True,
                    "usage_multiplier": 1,
                    "category": "coding"
                },
                {
                    "id": "claude-4-5-sonnet-thinking",
                    "display_name": "claude-4-5-sonnet-thinking",
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


# GraphQL 模型列表缓存
_model_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: Optional[datetime] = None
_cache_lock = asyncio.Lock()
CACHE_DURATION = timedelta(hours=1)  # 缓存1小时

# GraphQL 查询语句
GRAPHQL_QUERY = """
query GetFeatureModelChoices($requestContext: RequestContext!) {
  user(requestContext: $requestContext) {
    __typename
    ... on UserOutput {
      user {
        workspaces {
          featureModelChoice {
            agentMode {
              defaultId
              choices {
                displayName
                id
                usageMetadata {
                  creditMultiplier
                  requestMultiplier
                }
                description
                disableReason
                visionSupported
                spec {
                  cost
                  quality
                  speed
                }
                provider
              }
            }
            planning {
              defaultId
              choices {
                displayName
                id
                usageMetadata {
                  creditMultiplier
                  requestMultiplier
                }
                description
                disableReason
                visionSupported
                spec {
                  cost
                  quality
                  speed
                }
                provider
              }
            }
            coding {
              defaultId
              choices {
                displayName
                id
                usageMetadata {
                  creditMultiplier
                  requestMultiplier
                }
                description
                disableReason
                visionSupported
                spec {
                  cost
                  quality
                  speed
                }
                provider
              }
            }
          }
        }
      }
    }
  }
}
"""


async def fetch_warp_models_from_api(jwt_token: str) -> Optional[Dict[str, Any]]:
    """
    从 Warp GraphQL API 获取模型列表
    
    Args:
        jwt_token: Firebase JWT 认证令牌
        
    Returns:
        包含模型数据的字典，失败返回 None
    """
    try:
        from .settings import CLIENT_VERSION, OS_CATEGORY, OS_NAME, OS_VERSION
        
        url = "https://app.warp.dev/graphql/v2"
        
        headers = {
            "x-warp-client-id": "warp-app",
            "x-warp-client-version": CLIENT_VERSION,
            "x-warp-os-category": OS_CATEGORY,
            "x-warp-os-name": OS_NAME,
            "x-warp-os-version": OS_VERSION,
            "content-type": "application/json",
            "authorization": f"Bearer {jwt_token}",
            "accept": "*/*",
        }
        
        variables = {
            "requestContext": {
                "clientContext": {
                    "version": CLIENT_VERSION
                },
                "osContext": {
                    "category": OS_CATEGORY,
                    "linuxKernelVersion": None,
                    "name": OS_NAME,
                    "version": OS_VERSION
                }
            }
        }
        
        payload = {
            "query": GRAPHQL_QUERY,
            "variables": variables,
            "operationName": "GetFeatureModelChoices"
        }
        
        async with httpx.AsyncClient(timeout=10.0, trust_env=True) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code != 200:
                return None
                
            data = response.json()
            
            # 验证响应结构
            if not data.get("data", {}).get("user", {}).get("user", {}).get("workspaces"):
                return None
                
            return data
            
    except Exception as e:
        # 静默失败，降级到硬编码列表
        return None


def _convert_warp_model_to_openai(model: Dict[str, Any], category: str) -> Dict[str, Any]:
    """
    将 Warp 模型格式转换为 OpenAI 兼容格式
    
    Args:
        model: Warp 模型数据
        category: 模型分类（agentMode/planning/coding）
        
    Returns:
        OpenAI 格式的模型数据
    """
    return {
        "id": model.get("id", "unknown"),
        "object": "model",
        "created": int(time.time()),
        "owned_by": "warp",
        "display_name": model.get("displayName", model.get("id", "")),
        "description": model.get("description"),
        "vision_supported": model.get("visionSupported", False),
        "provider": model.get("provider", "UNKNOWN"),
        "spec": model.get("spec", {}),
        "usage_metadata": model.get("usageMetadata", {}),
        "disable_reason": model.get("disableReason"),
        "categories": [category],
    }


async def get_models_from_warp_api(jwt_token: str, use_cache: bool = True) -> List[Dict[str, Any]]:
    """
    从 Warp API 获取模型列表（带缓存）
    
    Args:
        jwt_token: Firebase JWT 认证令牌
        use_cache: 是否使用缓存（默认 True）
        
    Returns:
        OpenAI 格式的模型列表
    """
    global _model_cache, _cache_timestamp
    
    # 检查缓存
    if use_cache and _model_cache and _cache_timestamp:
        if datetime.now() - _cache_timestamp < CACHE_DURATION:
            return _model_cache
    
    async with _cache_lock:
        # 双重检查（防止并发请求）
        if use_cache and _model_cache and _cache_timestamp:
            if datetime.now() - _cache_timestamp < CACHE_DURATION:
                return _model_cache
        
        # 从 API 获取
        api_data = await fetch_warp_models_from_api(jwt_token)
        
        if not api_data:
            # API 失败，返回硬编码列表
            return get_all_unique_models()
        
        try:
            # 解析响应
            workspaces = api_data["data"]["user"]["user"]["workspaces"]
            if not workspaces:
                return get_all_unique_models()
            
            feature_model_choice = workspaces[0].get("featureModelChoice", {})
            
            unique_models: Dict[str, Dict[str, Any]] = {}
            
            # 处理三个类别
            for category_key, category_name in [
                ("agentMode", "agent"),
                ("planning", "planning"),
                ("coding", "coding")
            ]:
                category_data = feature_model_choice.get(category_key, {})
                choices = category_data.get("choices", [])
                
                for model in choices:
                    model_id = model.get("id")
                    if not model_id:
                        continue
                    
                    if model_id not in unique_models:
                        unique_models[model_id] = _convert_warp_model_to_openai(model, category_name)
                    else:
                        # 模型在多个分类中，添加分类
                        if category_name not in unique_models[model_id]["categories"]:
                            unique_models[model_id]["categories"].append(category_name)
            
            result = list(unique_models.values())
            
            # 更新缓存
            _model_cache = result
            _cache_timestamp = datetime.now()
            
            return result
            
        except Exception:
            # 解析失败，返回硬编码列表
            return get_all_unique_models()


def clear_model_cache():
    """清除模型缓存"""
    global _model_cache, _cache_timestamp
    _model_cache = None
    _cache_timestamp = None 