#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账号池认证模块
从账号池服务获取账号，替代临时账号注册
"""

import asyncio
import os
import time
from typing import Optional, Dict, Any

import httpx

from .auth import update_env_file
from .logging import logger
from .proxy_manager import AsyncProxyManager

# 账号池服务配置
POOL_SERVICE_URL = os.getenv("POOL_SERVICE_URL", "http://localhost:8019")
USE_POOL_SERVICE = os.getenv("USE_POOL_SERVICE", "true").lower() == "true"


class PoolAuthManager:
    """账号池认证管理器 (无状态设计，适合并发)"""

    def __init__(self):
        self.pool_url = POOL_SERVICE_URL

    async def acquire_session(self) -> Optional[Dict[str, Any]]:
        """
        从账号池获取一个新的会话（包含令牌和会话ID）。

        Returns:
            一个包含 'access_token', 'session_id', 'account' 的字典，或者在失败时返回 None。
        """
        logger.info(f"正在从账号池服务获取新会话: {self.pool_url}")

        try:
            client_config = {
                "timeout": httpx.Timeout(30.0),
                "verify": False,
                "trust_env": True
            }

            async with httpx.AsyncClient(**client_config) as client:
                # 分配账号
                response = await client.post(
                    f"{self.pool_url}/api/accounts/allocate",
                    json={"count": 1}
                )

                if response.status_code != 200:
                    logger.error(f"分配账号失败: HTTP {response.status_code} {response.text}")
                    return None

                data = response.json()

                if not data.get("success"):
                    logger.error(f"分配账号失败: {data.get('message', '未知错误')}")
                    return None

                accounts = data.get("accounts", [])
                if not accounts:
                    logger.error("账号池未返回任何账号")
                    return None

                account = accounts[0]
                session_id = data.get("session_id")

                logger.info(f"✅ 成功获得新账号: {account.get('email', 'N/A')}, 会话ID: {session_id}")

                # 获取访问令牌
                access_token = await self._get_access_token_from_account(account)
                if not access_token:
                    # 如果获取token失败，也应该释放会话
                    await self.release_session(session_id)
                    return None

                # 更新环境变量（用于兼容可能依赖它的旧代码）
                update_env_file(access_token)

                return {
                    "session_id": session_id,
                    "account": account,
                    "access_token": access_token,
                    "created_at": time.time()
                }

        except Exception as e:
            logger.error(f"从账号池获取会话时发生异常: {e}")
            return None

    async def _get_access_token_from_account(self, account: Dict[str, Any]) -> Optional[str]:
        """
        从账号信息获取访问令牌

        Args:
            account: 账号信息

        Returns:
            访问令牌或None
        """
        # 使用账号的refresh_token获取新的access_token
        refresh_token = account.get("refresh_token")
        id_token = account.get("id_token")  # 备用token

        if not refresh_token:
            # 如果没有refresh_token，直接使用id_token
            if id_token:
                logger.warning("账号缺少refresh_token，直接使用id_token")
                return id_token
            logger.error("账号缺少任何有效令牌")
            return None

        # 调用Warp的token刷新接口
        refresh_url = os.getenv("REFRESH_URL",
                                "https://app.warp.dev/proxy/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs")

        payload = f"grant_type=refresh_token&refresh_token={refresh_token}".encode("utf-8")
        headers = {
            "x-warp-client-version": os.getenv("CLIENT_VERSION", "v0.2025.08.06.08.12.stable_02"),
            "x-warp-os-category": os.getenv("OS_CATEGORY", "Darwin"),
            "x-warp-os-name": os.getenv("OS_NAME", "macOS"),
            "x-warp-os-version": os.getenv("OS_VERSION", "14.0"),
            "content-type": "application/x-www-form-urlencoded",
            "accept": "*/*",
            "accept-encoding": "gzip, br",
            "content-length": str(len(payload))
        }

        # 创建代理管理器
        proxy_manager = AsyncProxyManager()
        max_proxy_retries = 3

        for proxy_attempt in range(max_proxy_retries):
            try:
                # 获取代理
                proxy_str = await proxy_manager.get_proxy()
                proxy_config = None

                if proxy_str:
                    proxy_config = proxy_manager.format_proxy_for_httpx(proxy_str)
                    # logger.info(f"账号Token刷新使用代理: {proxy_config[:30]}..." if proxy_config else "直连")
                else:
                    logger.warning("账号Token刷新无法获取代理，使用直连")

                client_config = {
                    "timeout": httpx.Timeout(30.0),
                    "verify": False,
                    "trust_env": True
                }

                if proxy_config:
                    client_config["proxy"] = proxy_config

                async with httpx.AsyncClient(**client_config) as client:
                    resp = await client.post(refresh_url, headers=headers, content=payload)
                    if resp.status_code == 200:
                        token_data = resp.json()
                        access_token = token_data.get("access_token")

                        if not access_token:
                            # 如果没有access_token，使用id_token
                            access_token = account.get("id_token") or token_data.get("id_token")
                            if access_token:
                                logger.warning("使用id_token作为访问令牌")
                                return access_token
                            logger.error(f"响应中无访问令牌: {token_data}")
                            return None

                        logger.info("成功刷新访问令牌")
                        return access_token
                    else:
                        # 如果刷新失败，尝试使用id_token
                        if proxy_attempt < max_proxy_retries - 1:
                            logger.warning(
                                f"账号Token刷新失败，尝试换代理 (attempt {proxy_attempt + 1}/{max_proxy_retries})"
                            )
                            await asyncio.sleep(0.5)
                            continue

                        logger.warning(f"刷新令牌失败，尝试使用id_token")
                        if id_token:
                            return id_token
                        return None

            except (httpx.ConnectError, httpx.ProxyError, httpx.RemoteProtocolError) as ssl_error:
                logger.warning(
                    f"账号Token刷新 SSL/代理错误 (attempt {proxy_attempt + 1}/{max_proxy_retries}): {ssl_error}"
                )
                if proxy_attempt < max_proxy_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                # 最后尝试使用id_token
                if id_token:
                    logger.warning("由于网络错误，使用id_token作为备用")
                    return id_token
                return None

            except Exception as e:
                logger.error(f"刷新令牌时发生异常: {e}")
                if proxy_attempt < max_proxy_retries - 1:
                    await asyncio.sleep(0.5)
                    continue
                if id_token:
                    return id_token
                return None

        # 所有重试都失败了
        logger.error("刷新令牌在多次尝试后均失败")
        return id_token  # 最后尝试返回id_token

    async def release_session(self, session_id: Optional[str]):
        """根据会话ID释放会话"""
        if not session_id:
            return

        logger.info(f"正在释放会话: {session_id}")

        try:
            client_config = {
                "timeout": httpx.Timeout(10.0),
                "verify": False,
                "trust_env": True
            }

            async with httpx.AsyncClient(**client_config) as client:
                response = await client.post(
                    f"{self.pool_url}/api/accounts/release",
                    json={"session_id": session_id}
                )

                if response.status_code == 200:
                    logger.info(f"✅ 成功释放会话: {session_id}")
                else:
                    logger.warning(f"释放会话失败: HTTP {response.status_code}")
                return  # 无论成功失败，都退出

        except Exception as e:
            logger.error(f"释放会话时发生异常: {e}")


# 全局管理器实例（无状态，可安全共享）
_pool_manager = None


def get_pool_manager() -> PoolAuthManager:
    """获取账号池管理器实例"""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = PoolAuthManager()
    return _pool_manager


async def acquire_pool_or_anonymous_token(force_new: bool = False) -> Optional[str]:
    """
    获取访问令牌（优先从账号池，失败则创建临时账号）

    Returns:
        访问令牌字符串或None
    """
    if USE_POOL_SERVICE:
        try:
            # 从账号池获取新会话
            manager = get_pool_manager()
            session = await manager.acquire_session()
            if session and session.get("access_token"):
                return session["access_token"]
            logger.warning("账号池服务获取会话失败，降级到临时账号")
        except Exception as e:
            logger.warning(f"账号池服务不可用，降级到临时账号: {e}")

    # 降级到原来的临时账号逻辑
    from .auth import acquire_anonymous_access_token
    try:
        return await acquire_anonymous_access_token()
    except Exception as e:
        logger.error(f"获取临时账号失败: {e}")
        return None


async def acquire_pool_session_with_info() -> Optional[Dict[str, Any]]:
    """
    获取带完整会话信息的账号（包括session_id用于后续释放）

    Returns:
        包含 access_token, session_id, account 的字典，或None
    """
    if USE_POOL_SERVICE:
        try:
            manager = get_pool_manager()
            session = await manager.acquire_session()
            if session:
                return session
            logger.warning("账号池服务获取会话失败，降级到临时账号")
        except Exception as e:
            logger.warning(f"账号池服务不可用，降级到临时账号: {e}")

    # 降级逻辑：创建临时账号
    from .auth import acquire_anonymous_access_token
    try:
        temp_token = await acquire_anonymous_access_token()
        if temp_token:
            # 临时账号没有会话ID需要管理
            return {
                "access_token": temp_token,
                "session_id": None,
                "account": {"email": "anonymous"},
                "created_at": time.time()
            }
    except Exception as e:
        logger.error(f"创建临时匿名账号失败: {e}")

    return None


async def release_pool_session(session_id: Optional[str] = None):
    """
    释放账号池会话

    Args:
        session_id: 要释放的会话ID，如果为None则不执行任何操作
    """
    if USE_POOL_SERVICE and session_id:
        try:
            manager = get_pool_manager()
            await manager.release_session(session_id)
        except Exception as e:
            logger.error(f"释放会话失败: {e}")


def get_current_account_info() -> Optional[Dict[str, Any]]:
    """
    获取当前账号信息（兼容性接口，新架构中不再有"当前"账号概念）

    Returns:
        None（因为新架构中没有全局当前账号）
    """
    logger.warning("get_current_account_info在新架构中已弃用，返回None")
    return None
