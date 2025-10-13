from __future__ import annotations

import json
import time
import uuid
import asyncio
from typing import Any, Dict, Optional

import httpx
from .logging import logger

from .config import (
    BRIDGE_BASE_URL,
    FALLBACK_BRIDGE_URLS,
    WARMUP_INIT_RETRIES,
    WARMUP_INIT_DELAY_S,
    WARMUP_REQUEST_RETRIES,
    WARMUP_REQUEST_DELAY_S,
)
from .packets import packet_template
from .state import GLOBAL_BASELINE, ensure_tool_ids, STATE

# 创建一个全局的、可复用的 httpx.AsyncClient 实例以提高性能
_http_client: Optional[httpx.AsyncClient] = None
_initialization_lock = asyncio.Lock()
_initialized = False


def get_http_client() -> httpx.AsyncClient:
    """获取或创建全局 HTTP 客户端"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=200, max_connections=400),
            trust_env=True
        )
    return _http_client


async def bridge_send_stream(packet: Dict[str, Any]) -> Dict[str, Any]:
    """异步发送数据流到 bridge 服务"""
    last_exc: Optional[Exception] = None
    client = get_http_client()

    for base in FALLBACK_BRIDGE_URLS:
        url = f"{base}/api/warp/send_stream"
        try:
            wrapped_packet = {"json_data": packet, "message_type": "warp.multi_agent.v1.Request"}

            # try:
            #     logger.info("[OpenAI Compat] Bridge request URL: %s", url)
            #     logger.info("[OpenAI Compat] Bridge request payload: %s",
            #                 json.dumps(wrapped_packet, ensure_ascii=False))
            # except Exception:
            #     logger.info("[OpenAI Compat] Bridge request payload serialization failed for URL %s", url)

            # 使用全局的 httpx.AsyncClient 实例发送异步请求
            r = await client.post(url, json=wrapped_packet)

            if r.status_code == 200:
                try:
                    logger.info("[OpenAI Compat] Bridge response (raw text): %s", r.text)
                except Exception:
                    pass
                return r.json()
            else:
                txt = r.text
                last_exc = Exception(f"bridge_error: HTTP {r.status_code} {txt}")

        except httpx.ReadTimeout:
            # logger.warning(f"[OpenAI Compat] Request timeout for {url}, trying next fallback")
            last_exc = Exception("Request timeout")
            continue

        except Exception as e:
            last_exc = e
            continue

    if last_exc:
        raise last_exc
    raise Exception("bridge_unreachable")
#
#
# async def initialize_once() -> None:
#     """异步地、线程安全地执行一次性初始化"""
#     global _initialized
#
#     # 快速检查，避免不必要的加锁开销
#     if _initialized:
#         return
#
#     async with _initialization_lock:
#         # 在锁内再次检查，防止并发进入
#         if _initialized:
#             return
#
#         logger.info("[OpenAI Compat] Starting one-time initialization...")
#
#         ensure_tool_ids()
#
#         first_task_id = STATE.baseline_task_id or str(uuid.uuid4())
#         STATE.baseline_task_id = first_task_id
#
#         client = get_http_client()
#         health_urls = [f"{base}/healthz" for base in FALLBACK_BRIDGE_URLS]
#         last_err: Optional[str] = None
#
#         for _ in range(WARMUP_INIT_RETRIES):
#             try:
#                 ok = False
#                 last_err = None
#                 for h in health_urls:
#                     try:
#                         resp = await client.get(h, timeout=5.0)
#                         if resp.status_code == 200:
#                             ok = True
#                             break
#                         else:
#                             last_err = f"HTTP {resp.status_code} at {h}"
#                     except Exception as he:
#                         last_err = f"{type(he).__name__}: {he} at {h}"
#                 if ok:
#                     break
#             except Exception as e:
#                 last_err = str(e)
#             await asyncio.sleep(WARMUP_INIT_DELAY_S)
#         else:
#             # 注意：我们不再抛出异常，只是记录警告
#             logger.warning(f"Bridge server not ready during init: {last_err}")
#
#         pkt = packet_template()
#         pkt["task_context"]["active_task_id"] = first_task_id
#         pkt["input"]["user_inputs"]["inputs"].append({"user_query": {"query": "warmup"}})
#
#         last_exc: Optional[Exception] = None
#         for attempt in range(1, WARMUP_REQUEST_RETRIES + 1):
#             try:
#                 resp = await bridge_send_stream(pkt)
#                 # ================ 关键修改 ================
#                 # 将结果存入真正的全局对象，而不是临时的上下文状态
#                 GLOBAL_BASELINE.conversation_id = resp.get("conversation_id") or GLOBAL_BASELINE.conversation_id
#                 ret_task_id = resp.get("task_id")
#                 if isinstance(ret_task_id, str) and ret_task_id:
#                     GLOBAL_BASELINE.baseline_task_id = ret_task_id
#                 # ==========================================
#                 break
#             except Exception as e:
#                 last_exc = e
#                 logger.warning(f"[OpenAI Compat] Warmup attempt {attempt}/{WARMUP_REQUEST_RETRIES} failed: {e}")
#                 if attempt < WARMUP_REQUEST_RETRIES:
#                     await asyncio.sleep(WARMUP_REQUEST_DELAY_S)
#
#         # 即使预热失败，我们也标记为已初始化，避免重复尝试
#         _initialized = True
#
#         if last_exc:
#             logger.warning(f"[OpenAI Compat] Initialization completed with warnings: {last_exc}")
#         else:
#             logger.info("[OpenAI Compat] One-time initialization completed successfully.")
#             logger.info(f"[OpenAI Compat] Global baseline set: conversation_id='{GLOBAL_BASELINE.conversation_id}', baseline_task_id='{GLOBAL_BASELINE.baseline_task_id}'")


async def initialize_once() -> None:
    """异步地、线程安全地执行一次性初始化"""
    global _initialized

    # 快速检查，避免不必要的加锁开销
    if _initialized:
        return

    async with _initialization_lock:
        # 在锁内再次检查，防止并发进入
        if _initialized:
            return

        ensure_tool_ids()

        first_task_id = STATE.baseline_task_id or str(uuid.uuid4())
        STATE.baseline_task_id = first_task_id

        client = get_http_client()
        health_urls = [f"{base}/healthz" for base in FALLBACK_BRIDGE_URLS]
        last_err: Optional[str] = None

        for _ in range(WARMUP_INIT_RETRIES):
            try:
                ok = False
                last_err = None
                for h in health_urls:
                    try:
                        resp = await client.get(h, timeout=5.0)
                        if resp.status_code == 200:
                            ok = True
                            break
                        else:
                            last_err = f"HTTP {resp.status_code} at {h}"
                    except Exception as he:
                        last_err = f"{type(he).__name__}: {he} at {h}"
                if ok:
                    break
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(WARMUP_INIT_DELAY_S)
        else:
            # 注意：我们不再抛出异常，只是记录警告
            logger.warning(f"Bridge server not ready during init: {last_err}")

        # 即使预热失败，我们也标记为已初始化，避免重复尝试
        _initialized = True
