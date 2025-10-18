#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp账号池维护脚本
管理已注册的账号，包括token刷新、状态检查等
"""

import asyncio
import sqlite3
import json
import time
import base64
import traceback

import requests
import os
from typing import Union
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

# ==================== 配置部分 ====================
import config

# 日志配置
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================
@dataclass
class Account:
    """账号数据模型"""
    id: Optional[int] = None
    email: str = ""
    email_password: Optional[str] = None
    local_id: str = ""
    id_token: str = ""
    refresh_token: str = ""
    status: str = "active"
    created_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    last_refresh_time: Optional[datetime] = None
    use_count: int = 0
    proxy_info: Optional[str] = None
    user_agent: Optional[str] = None


# ==================== 数据库管理 ====================
class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path=config.DATABASE_PATH):
        self.db_path = db_path

    def get_all_accounts(self, status: str = None) -> List[Account]:
        """获取所有账号"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if status:
            cursor.execute('SELECT * FROM accounts WHERE status = ?', (status,))
        else:
            cursor.execute('SELECT * FROM accounts')

        rows = cursor.fetchall()
        accounts = []

        for row in rows:
            account = Account(
                id=row['id'],
                email=row['email'],
                email_password=row['email_password'],
                local_id=row['local_id'],
                id_token=row['id_token'],
                refresh_token=row['refresh_token'],
                status=row['status'],
                created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                last_used=datetime.fromisoformat(row['last_used']) if row['last_used'] else None,
                last_refresh_time=datetime.fromisoformat(row['last_refresh_time']) if row[
                    'last_refresh_time'] else None,
                use_count=row['use_count'] or 0,
                proxy_info=row['proxy_info'],
                user_agent=row['user_agent']
            )
            accounts.append(account)

        conn.close()
        return accounts

    def update_account_token(self, email: str, id_token: str, refresh_token: str = None):
        """更新账号token"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if refresh_token:
            cursor.execute('''
                           UPDATE accounts
                           SET id_token          = ?,
                               refresh_token     = ?,
                               last_refresh_time = ?
                           WHERE email = ?
                           ''', (id_token, refresh_token, datetime.now(), email))
        else:
            cursor.execute('''
                           UPDATE accounts
                           SET id_token          = ?,
                               last_refresh_time = ?
                           WHERE email = ?
                           ''', (id_token, datetime.now(), email))

        conn.commit()
        conn.close()
        logger.info(f"✅ 更新账号token: {email}")

    def update_account_status(self, email: str, status: str):
        """更新账号状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
                       UPDATE accounts
                       SET status = ?
                       WHERE email = ?
                       ''', (status, email))

        conn.commit()
        conn.close()
        logger.info(f"📝 更新账号状态: {email} -> {status}")

    def get_statistics(self) -> Dict[str, int]:
        """获取统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}
        cursor.execute('SELECT status, COUNT(*) FROM accounts GROUP BY status')
        for row in cursor.fetchall():
            stats[row[0]] = row[1]

        cursor.execute('SELECT COUNT(*) FROM accounts')
        stats['total'] = cursor.fetchone()[0]

        conn.close()
        return stats

    def cleanup_expired_accounts(self, days: int = 30):
        """清理过期账号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 删除30天未使用的账号
        cutoff_date = datetime.now() - timedelta(days=days)
        cursor.execute('''
                       DELETE
                       FROM accounts
                       WHERE status = 'expired'
                          OR (last_used IS NOT NULL AND last_used < ?)
                       ''', (cutoff_date,))

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            logger.info(f"🗑️ 清理了 {deleted_count} 个过期账号")

        return deleted_count


# ==================== Token刷新服务 ====================
class TokenRefreshService:
    """Token刷新服务"""

    def __init__(self, firebase_api_key: str = config.FIREBASE_API_KEY):
        self.firebase_api_key = firebase_api_key
        self.base_url = "https://securetoken.googleapis.com/v1/token"
        # 代理（如配置）
        self.proxies = None
        if getattr(config, 'PROXY_URL', None):
            self.proxies = {
                'http': config.PROXY_URL,
                'https': config.PROXY_URL
            }
            logger.info(f"🌐 使用代理: {config.PROXY_URL}")

        # TLS 验证：支持关闭或使用自定义 CA Bundle
        # 优先环境变量 REQUESTS_CA_BUNDLE，其次 config.CA_BUNDLE_PATH，其次 config.SSL_NO_VERIFY
        self.verify: Union[bool, str] = True
        ca_bundle = os.environ.get('REQUESTS_CA_BUNDLE') or getattr(config, 'CA_BUNDLE_PATH', None)
        if ca_bundle:
            self.verify = ca_bundle
            logger.info(f"🔐 使用自定义CA证书: {ca_bundle}")
        elif getattr(config, 'SSL_NO_VERIFY', False):
            self.verify = False
            logger.warning("⚠️ 已禁用TLS证书校验 (仅用于调试)")

    def is_token_expired(self, id_token: str, buffer_minutes: int = 5) -> bool:
        """检查JWT token是否过期"""
        try:
            if not id_token:
                return True

            # 解码JWT token
            parts = id_token.split('.')
            if len(parts) != 3:
                return True

            # 解码payload
            payload_part = parts[1]
            payload_part += '=' * (4 - len(payload_part) % 4)

            payload_bytes = base64.urlsafe_b64decode(payload_part)
            payload = json.loads(payload_bytes.decode('utf-8'))

            # 检查过期时间
            exp_timestamp = payload.get('exp')
            if not exp_timestamp:
                return True

            # 添加缓冲时间
            current_time = time.time()
            buffer_seconds = buffer_minutes * 60

            return (exp_timestamp - current_time) <= buffer_seconds

        except Exception as e:
            logger.error(f"检查Token过期状态失败: {e}")
            return True

    def can_refresh_token(self, account: Account) -> Tuple[bool, Optional[str]]:
        """检查是否可以刷新token（遵守1小时限制）"""
        if not account.last_refresh_time:
            return True, None

        # 检查时间间隔
        time_elapsed = datetime.now() - account.last_refresh_time
        min_interval = timedelta(hours=config.TOKEN_REFRESH_HOURS)

        if time_elapsed >= min_interval:
            return True, None
        else:
            remaining = min_interval - time_elapsed
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            return False, f"需要等待 {minutes}分{seconds}秒"

    def refresh_firebase_token(self, refresh_token: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """刷新Firebase Token"""
        try:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }

            url = f"{self.base_url}?key={self.firebase_api_key}"

            response = requests.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "warp-pool-maintenance/1.0"
                },
                timeout=30,
                proxies=self.proxies,
                verify=self.verify,
            )

            if response.ok:
                data = response.json()
                new_id_token = data.get('id_token')
                if new_id_token:
                    logger.info("✅ Firebase Token刷新成功")
                    return True, new_id_token, None

            return False, None, f"HTTP {response.status_code}"

        except Exception as e:
            return False, None, str(e)

    async def refresh_account_if_needed(self, account: Account, db_manager: DatabaseManager) -> bool:
        """根据需要刷新账号token"""
        # 检查是否过期
        if not self.is_token_expired(account.id_token, buffer_minutes=10):
            return True

        # 检查是否可以刷新
        can_refresh, error_msg = self.can_refresh_token(account)
        if not can_refresh:
            logger.warning(f"⏰ {account.email} - {error_msg}")
            return False

        # 执行刷新
        success, new_token, error = self.refresh_firebase_token(account.refresh_token)
        if success and new_token:
            db_manager.update_account_token(account.email, new_token)
            logger.info(f"✨ 刷新token成功: {account.email}")
            return True
        else:
            logger.error(f"❌ 刷新token失败: {account.email} - {error}")
            return False


# ==================== 账号池维护器 ====================
class PoolMaintainer:
    """账号池维护器"""

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.token_refresh_service = TokenRefreshService()
        self.running = False

    async def check_pool_health(self):
        """检查账号池健康状态"""
        stats = self.db_manager.get_statistics()
        total = stats.get('total', 0)
        active = stats.get('active', 0)
        expired = stats.get('expired', 0)

        logger.info("=" * 50)
        logger.info("📊 账号池状态")
        logger.info(f"📦 总账号数: {total}")
        logger.info(f"✅ 活跃账号: {active}")
        logger.info(f"❌ 过期账号: {expired}")

        # 健康评估
        if active < config.MIN_POOL_SIZE:
            logger.warning(f"⚠️ 活跃账号不足 (当前: {active}, 最小: {config.MIN_POOL_SIZE})")
        elif active > config.MAX_POOL_SIZE:
            logger.warning(f"⚠️ 活跃账号过多 (当前: {active}, 最大: {config.MAX_POOL_SIZE})")
        else:
            logger.info(f"💚 账号池健康")

        logger.info("=" * 50)

        return stats

    async def refresh_tokens(self):
        """批量刷新token"""
        logger.info("🔄 开始刷新token...")

        accounts = self.db_manager.get_all_accounts(status='active')
        refreshed = 0
        failed = 0
        skipped = 0

        for account in accounts:
            try:
                if await self.token_refresh_service.refresh_account_if_needed(account, self.db_manager):
                    refreshed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"刷新账号 {account.email} 失败: {e}")
                failed += 1

        logger.info(f"🔄 Token刷新完成 - 成功: {refreshed}, 跳过: {skipped}, 失败: {failed}")

    async def verify_accounts(self):
        """验证账号可用性"""
        logger.info("🔍 验证账号可用性...")

        accounts = self.db_manager.get_all_accounts(status='active')
        verified = 0
        invalid = 0

        for account in accounts:
            try:
                # 简单验证token格式
                if account.id_token and len(account.id_token.split('.')) == 3:
                    verified += 1
                else:
                    self.db_manager.update_account_status(account.email, 'expired')
                    invalid += 1
            except Exception as e:
                logger.error(f"验证账号 {account.email} 失败: {e}")
                invalid += 1

        logger.info(f"🔍 账号验证完成 - 有效: {verified}, 无效: {invalid}")

    async def cleanup(self):
        """清理任务"""
        logger.info("🗑️ 执行清理任务...")

        # 清理过期账号
        deleted = self.db_manager.cleanup_expired_accounts(days=30)
        logger.info(f"🗑️ 清理完成，删除 {deleted} 个过期账号")

    async def maintenance_loop(self):
        """维护循环"""
        logger.info("🔧 账号池维护服务启动")

        cycle = 0
        while self.running:
            cycle += 1
            logger.info(f"\n🔄 第 {cycle} 个维护周期开始")

            try:
                # 1. 检查池健康状态
                await self.check_pool_health()

                # 2. 刷新即将过期的token
                await self.refresh_tokens()

                # 3. 验证账号可用性
                await self.verify_accounts()

                # 4. 每10个周期执行一次清理
                if cycle % 10 == 0:
                    await self.cleanup()

                logger.info(f"✅ 第 {cycle} 个维护周期完成")

            except Exception as e:
                logger.error(f"❌ 维护周期异常: {e}")
                logging.error(f"详细错误: {traceback.format_exc()}")

            # 等待下一个周期
            logger.info(f"⏰ 等待 {config.MAINTENANCE_CHECK_INTERVAL} 秒后进行下一次检查...")
            await asyncio.sleep(config.MAINTENANCE_CHECK_INTERVAL)

    async def start(self):
        """启动维护服务"""
        self.running = True

        try:
            await self.maintenance_loop()
        except KeyboardInterrupt:
            logger.info("⌨️ 收到停止信号")
        finally:
            self.running = False
            logger.info("🛑 维护服务已停止")

    async def manual_refresh(self, email: str = None, force: bool = False):
        """手动刷新指定账号或所有账号"""
        if email:
            accounts = [acc for acc in self.db_manager.get_all_accounts() if acc.email == email]
            if not accounts:
                logger.error(f"账号不存在: {email}")
                return
        else:
            accounts = self.db_manager.get_all_accounts(status='active')

        logger.info(f"📋 手动刷新 {len(accounts)} 个账号")

        for account in accounts:
            try:
                if force:
                    # 强制刷新
                    success, new_token, error = self.token_refresh_service.refresh_firebase_token(account.refresh_token)
                    if success and new_token:
                        self.db_manager.update_account_token(account.email, new_token)
                        logger.info(f"✅ 强制刷新成功: {account.email}")
                    else:
                        logger.error(f"❌ 强制刷新失败: {account.email} - {error}")
                else:
                    # 正常刷新
                    await self.token_refresh_service.refresh_account_if_needed(account, self.db_manager)

            except Exception as e:
                logger.error(f"刷新账号 {account.email} 时出错: {e}")


# ==================== 命令行接口 ====================
async def interactive_mode():
    """交互模式"""
    maintainer = PoolMaintainer()

    print("\n" + "=" * 60)
    print("🎮 Warp账号池维护 - 交互模式")
    print("=" * 60)
    print("命令列表:")
    print("  status  - 查看账号池状态")
    print("  refresh - 刷新所有账号token")
    print("  verify  - 验证账号可用性")
    print("  clean   - 清理过期账号")
    print("  auto    - 启动自动维护")
    print("  exit    - 退出程序")
    print("=" * 60)

    while True:
        try:
            cmd = input("\n> ").strip().lower()

            if cmd == "status":
                await maintainer.check_pool_health()
            elif cmd == "refresh":
                await maintainer.refresh_tokens()
            elif cmd == "verify":
                await maintainer.verify_accounts()
            elif cmd == "clean":
                await maintainer.cleanup()
            elif cmd == "auto":
                print("🔧 启动自动维护模式...")
                await maintainer.start()
            elif cmd == "exit":
                print("👋 再见!")
                break
            else:
                print(f"❓ 未知命令: {cmd}")

        except KeyboardInterrupt:
            print("\n👋 再见!")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")


# ==================== 主函数 ====================
async def main():
    """主函数"""
    import sys

    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

        if mode == "auto":
            # 自动模式
            logger.info("🔧 启动自动维护模式")
            maintainer = PoolMaintainer()
            await maintainer.start()
        elif mode == "interactive":
            # 交互模式
            await interactive_mode()
        else:
            print(f"❓ 未知模式: {mode}")
            print("用法: python pool_maintenance.py [auto|interactive]")
    else:
        # 默认自动模式
        logger.info("🔧 启动自动维护模式（默认）")
        maintainer = PoolMaintainer()
        await maintainer.start()


if __name__ == "__main__":
    asyncio.run(main())
