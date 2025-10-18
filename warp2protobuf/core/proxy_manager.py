# protobuf2openai/proxy_manager.py
import asyncio
import random
import httpx
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AsyncProxyManager:
    """异步代理管理器"""

    def __init__(self):
        self.used_identifiers = {}
        self.lock = asyncio.Lock()

    async def cleanup_expired_identifiers(self):
        """清理过期的IP标识"""
        current_time = datetime.now()
        async with self.lock:
            expired_keys = [k for k, v in self.used_identifiers.items() if v < current_time]
            for key in expired_keys:
                del self.used_identifiers[key]

    async def get_proxy(self) -> Optional[str]:
        """获取代理IP"""
        return "http://127.0.0.1:7890"  # 本地代理示例

    def format_proxy_for_httpx(self, proxy_str: str) -> Optional[str]:
        """格式化代理为httpx格式"""
        if not proxy_str:
            return None

        try:
            s = proxy_str.strip()
            # 若已包含协议前缀，直接返回（http/https/socks5/socks4）
            if s.startswith(("http://", "https://", "socks5://", "socks4://")):
                return s

            # 处理带鉴权的 host:port 形式，例如 user:pass@host:port
            if "@" in s:
                credentials, host_port = s.split("@", 1)
                user, password = credentials.split(":", 1)
                host, port = host_port.rsplit(":", 1)
                return f"socks5://{user}:{password}@{host}:{port}"
            else:
                # 普通 host:port，使用从右侧分割一次，避免 IPv6/额外冒号导致拆包错误
                host, port = s.rsplit(":", 1)
                return f"socks5://{host}:{port}"
        except Exception as e:
            logger.error(f"格式化代理失败: {e}")
            return None
