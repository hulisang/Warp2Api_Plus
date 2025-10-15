#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账号池HTTP服务
提供账号分配、释放、状态查询等API
"""

import asyncio
import logging
import time
import traceback
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

import aiosqlite
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==================== 配置 ====================
import config

# 日志配置
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================
class AllocateRequest(BaseModel):
    count: int = 1
    session_duration: Optional[int] = 1800  # 默认30分钟


class ReleaseRequest(BaseModel):
    session_id: str


class RefreshRequest(BaseModel):
    session_id: str
    account_email: str


class BlockAccountRequest(BaseModel):
    jwt_token: Optional[str] = None
    email: Optional[str] = None


class AddAccountFromLinkRequest(BaseModel):
    email: str
    login_link: str  # 支持邮箱链接或客户端重定向链接


class RefreshCreditsRequest(BaseModel):
    email: Optional[str] = None  # 为空则刷新所有账号

# ==================== Credits查询服务 ====================
class WarpCreditsService:
    """Warp账号Credits查询服务"""
    
    GRAPHQL_URL = "https://app.warp.dev/graphql/v2"
    FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
    WARP_CLIENT_VERSION = "v0.2025.10.08.08.12.stable_05"
    
    # GraphQL查询
    QUERY = """query GetRequestLimitInfo($requestContext: RequestContext!) {
  user(requestContext: $requestContext) {
    __typename
    ... on UserOutput {
      user {
        requestLimitInfo {
          isUnlimited
          nextRefreshTime
          requestLimit
          requestsUsedSinceLastRefresh
          requestLimitRefreshDuration
          isUnlimitedAutosuggestions
          acceptedAutosuggestionsLimit
          acceptedAutosuggestionsSinceLastRefresh
          isUnlimitedVoice
          voiceRequestLimit
          voiceRequestsUsedSinceLastRefresh
          voiceTokenLimit
          voiceTokensUsedSinceLastRefresh
          isUnlimitedCodebaseIndices
          maxCodebaseIndices
          maxFilesPerRepo
          embeddingGenerationBatchSize
          requestLimitPooling
        }
      }
    }
    ... on UserFacingError {
      error {
        __typename
        ... on SharedObjectsLimitExceeded {
          limit
          objectType
          message
        }
        ... on PersonalObjectsLimitExceeded {
          limit
          objectType
          message
        }
        ... on AccountDelinquencyError {
          message
        }
        ... on GenericStringObjectUniqueKeyConflict {
          message
        }
      }
      responseContext {
        serverVersion
      }
    }
  }
}
"""
    
    def __init__(self, proxy: Optional[str] = None):
        """初始化Credits服务"""
        self.proxy = proxy
    
    async def refresh_id_token(self, refresh_token: str) -> Optional[str]:
        """使用refresh_token刷新id_token"""
        try:
            logger.info(f"🔄 尝试刷新Token: refresh_token={refresh_token[:20]}...")
            
            client_kwargs = {"timeout": 30.0}
            if self.proxy:
                client_kwargs["proxy"] = self.proxy
                logger.info(f"🌐 使用代理: {self.proxy}")
            
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    self.FIREBASE_REFRESH_URL,
                    params={"key": config.FIREBASE_API_KEY},
                    json={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token
                    }
                )
                
                logger.info(f"📡 Firebase响应: HTTP {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    new_id_token = data.get("id_token")
                    new_refresh_token = data.get("refresh_token")
                    
                    if new_id_token:
                        logger.info(f"✅ Token刷新成功: {new_id_token[:30]}...")
                        return new_id_token
                    else:
                        logger.error("❌ 响应中未找到id_token")
                        return None
                else:
                    error_text = response.text[:200]
                    logger.error(f"❌ 刷新Token失败: HTTP {response.status_code}, 错误: {error_text}")
                    return None
        except Exception as e:
            logger.error(f"❌ 刷新Token异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    async def get_credits(self, id_token: str) -> Dict[str, Any]:
        """获取账号credits信息"""
        if not id_token:
            return {"success": False, "error": "缺少ID Token"}
        
        try:
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {id_token}",
                "x-warp-client-id": "warp-app",
                "x-warp-client-version": self.WARP_CLIENT_VERSION,
                "x-warp-os-category": "Windows",
                "x-warp-os-name": "Windows",
                "x-warp-os-version": "11 (26100)",
                "accept": "*/*",
                "accept-encoding": "gzip, br"
            }
            
            payload = {
                "operationName": "GetRequestLimitInfo",
                "variables": {
                    "requestContext": {
                        "clientContext": {"version": self.WARP_CLIENT_VERSION},
                        "osContext": {
                            "category": "Windows",
                            "linuxKernelVersion": None,
                            "name": "Windows",
                            "version": "11 (26100)"
                        }
                    }
                },
                "query": self.QUERY
            }
            
            # 构建httpx客户端参数
            client_kwargs = {"timeout": 30.0}
            if self.proxy:
                # httpx使用proxy参数而不是proxies
                client_kwargs["proxy"] = self.proxy
            
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    self.GRAPHQL_URL,
                    params={"op": "GetRequestLimitInfo"},
                    json=payload,
                    headers=headers
                )
                
                if response.status_code != 200:
                    return {"success": False, "error": f"HTTP {response.status_code}"}
                
                result = response.json()
                
                if "errors" in result:
                    return {"success": False, "error": result["errors"][0].get("message", "Unknown error")}
                
                data = result.get("data", {})
                user_data = data.get("user", {})
                
                if user_data.get("__typename") == "UserOutput":
                    request_limit_info = user_data.get("user", {}).get("requestLimitInfo", {})
                    
                    request_limit = request_limit_info.get("requestLimit", 0)
                    requests_used = request_limit_info.get("requestsUsedSinceLastRefresh", 0)
                    is_unlimited = request_limit_info.get("isUnlimited", False)
                    
                    # 根据Warp官方的额度规则判断账号类型
                    if is_unlimited:
                        quota_type = "Pro"  # 付费专业版（无限额度）
                    elif request_limit >= 2500:
                        quota_type = "Pro_Trial"  # Pro试用版（2500额度）
                    elif request_limit >= 150:
                        quota_type = "Free"  # 免费版（150额度）
                    else:
                        quota_type = "Unknown"  # 未知类型
                    
                    return {
                        "success": True,
                        "request_limit": request_limit,
                        "requests_used": requests_used,
                        "requests_remaining": request_limit - requests_used,
                        "is_unlimited": is_unlimited,
                        "quota_type": quota_type,
                        "next_refresh_time": request_limit_info.get("nextRefreshTime"),
                        "refresh_duration": request_limit_info.get("requestLimitRefreshDuration", "WEEKLY"),
                        "updated_at": datetime.now().isoformat()
                    }
                elif user_data.get("__typename") == "UserFacingError":
                    return {"success": False, "error": user_data.get("error", {}).get("message", "Unknown error")}
                else:
                    return {"success": False, "error": "未找到用户信息"}
        
        except httpx.TimeoutException:
            return {"success": False, "error": "请求超时"}
        except Exception as e:
            logger.error(f"获取credits失败: {e}")
            return {"success": False, "error": str(e)}


# ==================== 数据库优化器 ====================
class DatabaseOptimizer:
    """数据库性能优化器"""

    @staticmethod
    async def optimize_database(db_path: str):
        """优化数据库性能"""
        try:
            async with aiosqlite.connect(db_path) as db:
                # 创建索引以提升查询速度
                await db.execute("""
                                 CREATE INDEX IF NOT EXISTS idx_accounts_status_email
                                     ON accounts(status, email)
                                 """)

                await db.execute("""
                                 CREATE INDEX IF NOT EXISTS idx_accounts_status_last_used
                                     ON accounts(status, last_used)
                                 """)

                await db.execute("""
                                 CREATE INDEX IF NOT EXISTS idx_accounts_email
                                     ON accounts(email)
                                 """)

                # 优化数据库设置
                await db.execute("PRAGMA journal_mode = WAL")  # 使用WAL模式，提升并发性能
                await db.execute("PRAGMA synchronous = NORMAL")  # 平衡性能和安全性
                await db.execute("PRAGMA cache_size = 10000")  # 增加缓存大小
                await db.execute("PRAGMA temp_store = MEMORY")  # 使用内存存储临时数据

                await db.commit()
                logger.info("✅ 数据库优化完成")
        except Exception as e:
            logger.error(f"数据库优化失败: {e}")

# ==================== 账号池管理器 ====================
class AccountPoolManager:
    """账号池管理器"""

    def __init__(self, db_path: str = config.DATABASE_PATH):
        self.db_path = db_path
        self.sessions: Dict[str, Dict] = {}  # 会话管理
        self.locked_accounts: Dict[str, str] = {}  # email -> session_id
        self.lock = asyncio.Lock()
        self.account_cache: List[Dict] = []  # 账号缓存
        self.cache_updated_at = 0
        self.cache_ttl = 30  # 缓存有效期30秒
        self.credits_service = WarpCreditsService(proxy=config.PROXY_URL)  # Credits查询服务

    async def init_async(self):
        """异步初始化"""
        # 优化数据库
        await DatabaseOptimizer.optimize_database(self.db_path)
        # 预加载账号缓存
        await self.refresh_account_cache()

    async def refresh_account_cache(self):
        """刷新账号缓存"""
        try:
            async with aiosqlite.connect(self.db_path, timeout=config.DB_TIMEOUT) as db:
                db.row_factory = aiosqlite.Row

                # 只缓存活跃账号的基本信息
                cursor = await db.execute("""
                                          SELECT email,
                                                 local_id,
                                                 id_token,
                                                 refresh_token,
                                                 client_id,
                                                 outlook_refresh_token,
                                                 proxy_info,
                                                 user_agent,
                                                 email_password,
                                                 last_used,
                                                 created_at,
                                                 request_limit,
                                                 requests_remaining,
                                                 quota_type
                                          FROM accounts
                                          WHERE status = 'active'
                                          ORDER BY COALESCE(last_used, created_at) ASC
                                          """)

                rows = await cursor.fetchall()
                self.account_cache = [dict(row) for row in rows]
                self.cache_updated_at = time.time()

                logger.info(f"账号缓存已更新: {len(self.account_cache)} 个账号")
        except Exception as e:
            logger.error(f"刷新账号缓存失败: {e}")

    async def get_available_accounts_fast(self, count: int = 1) -> List[Dict[str, Any]]:
        """快速获取可用账号（使用缓存）"""
        # 检查缓存是否需要更新
        if time.time() - self.cache_updated_at > self.cache_ttl:
            asyncio.create_task(self.refresh_account_cache())  # 异步更新，不阻塞当前请求

        # 从缓存中找出未锁定的账号
        available = []
        for account in self.account_cache:
            if account['email'] not in self.locked_accounts:
                available.append(account)
                if len(available) >= count:
                    break

        return available

    async def allocate_accounts(self, count: int = 1, session_duration: int = config.MAX_SESSION_DURATION) -> Dict[str, Any]:
        """分配账号（优化版）"""
        start_time = time.time()

        try:
            # 使用超时锁，避免无限等待
            async with asyncio.timeout(3):  # 3秒超时
                async with self.lock:
                    logger.info(f"开始分配 {count} 个账号...")

                    # 快速获取可用账号
                    accounts = await self.get_available_accounts_fast(count)

                    if not accounts:
                        logger.warning("没有可用账号")
                        raise HTTPException(status_code=503, detail="No available accounts")

                    # 创建会话
                    session_id = str(uuid.uuid4())
                    session_info = {
                        'session_id': session_id,
                        'accounts': accounts,
                        'created_at': time.time(),
                        'expires_at': time.time() + session_duration,
                        'status': 'active'
                    }

                    # 锁定账号
                    for account in accounts:
                        self.locked_accounts[account['email']] = session_id

                    self.sessions[session_id] = session_info

                    # 异步更新数据库（不阻塞响应）
                    asyncio.create_task(self.update_last_used_async(accounts))

                    elapsed = time.time() - start_time
                    logger.info(f"✅ 分配了 {len(accounts)} 个账号，会话ID: {session_id}，耗时: {elapsed:.2f}秒")

                    return {
                        'success': True,
                        'session_id': session_id,
                        'accounts': accounts,
                        'expires_at': session_info['expires_at']
                    }

        except asyncio.TimeoutError:
            logger.error("分配账号超时")
            raise HTTPException(status_code=503, detail="Request timeout")
        except Exception as e:
            logger.error(f"分配账号失败: {e}")
            raise

    async def mark_account_blocked(self, jwt_token: Optional[str] = None, email: Optional[str] = None) -> Dict[str, Any]:
        """标记账号为已封禁"""
        try:
            async with aiosqlite.connect(self.db_path, timeout=config.DB_TIMEOUT) as db:
                found_email = None

                if email:
                    # 直接根据email标记
                    found_email = email
                elif jwt_token:
                    # 根据token片段查找账号
                    # 注意：这是简化实现，实际可能需要更复杂的匹配逻辑
                    cursor = await db.execute(
                        'SELECT email, id_token FROM accounts WHERE status = "active"'
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        # 粗略匹配token前缀（因为我们只传了前50个字符）
                        if row[1] and jwt_token in row[1][:50]:
                            found_email = row[0]
                            break

                if found_email:
                    # 更新数据库状态为blocked
                    await db.execute(
                        'UPDATE accounts SET status = "blocked", last_used = ? WHERE email = ?',
                        (datetime.now().isoformat(), found_email)
                    )
                    await db.commit()

                    # 从缓存中移除
                    self.account_cache = [
                        acc for acc in self.account_cache
                        if acc.get('email') != found_email
                    ]

                    # 从锁定列表中移除
                    if found_email in self.locked_accounts:
                        session_id = self.locked_accounts[found_email]
                        del self.locked_accounts[found_email]

                        # 更新会话信息
                        if session_id in self.sessions:
                            self.sessions[session_id]['accounts'] = [
                                acc for acc in self.sessions[session_id]['accounts']
                                if acc.get('email') != found_email
                            ]

                    logger.warning(f"⛔ 账号已标记为封禁: {found_email}")

                    return {
                        'success': True,
                        'message': f'Account {found_email} marked as blocked',
                        'email': found_email
                    }
                else:
                    return {
                        'success': False,
                        'message': 'Account not found'
                    }

        except Exception as e:
            logger.error(f"标记账号失败: {e}")
            return {
                'success': False,
                'message': str(e)
            }

    async def update_last_used_async(self, accounts: List[Dict]):
        """异步更新账号最后使用时间（后台任务）"""
        try:
            async with aiosqlite.connect(self.db_path, timeout=config.DB_TIMEOUT) as db:
                for account in accounts:
                    await db.execute(
                        'UPDATE accounts SET last_used = ?, use_count = use_count + 1 WHERE email = ?',
                        (datetime.now().isoformat(), account['email'])
                    )
                await db.commit()
                logger.info(f"已更新 {len(accounts)} 个账号的使用时间")
        except Exception as e:
            logger.error(f"更新账号使用时间失败: {e}")

    async def release_session(self, session_id: str) -> Dict[str, Any]:
        """释放会话"""
        try:
            async with asyncio.timeout(2):
                async with self.lock:
                    if session_id not in self.sessions:
                        return {
                            'success': False,
                            'message': 'Session not found'
                        }

                    session_info = self.sessions[session_id]

                    # 解锁账号
                    for account in session_info['accounts']:
                        if account['email'] in self.locked_accounts:
                            del self.locked_accounts[account['email']]

                    # 删除会话
                    del self.sessions[session_id]

                    logger.info(f"释放会话: {session_id}")

                    return {
                        'success': True,
                        'message': 'Session released'
                    }
        except asyncio.TimeoutError:
            return {
                'success': False,
                'message': 'Release timeout'
            }

    async def get_pool_status(self) -> Dict[str, Any]:
        """获取池状态（优化版）"""
        try:
            # 使用缓存的账号数量
            total_active = len(self.account_cache)
            locked_count = len(self.locked_accounts)
            available_count = total_active - locked_count

            # 异步获取过期账号数（不阻塞主查询）
            total_expired = 0
            try:
                async with aiosqlite.connect(self.db_path, timeout=2) as db:
                    cursor = await db.execute('SELECT COUNT(*) FROM accounts WHERE status = "expired"')
                    total_expired = (await cursor.fetchone())[0]
            except:
                pass

            return {
                'total_active': total_active,
                'total_expired': total_expired,
                'locked': locked_count,
                'available': available_count,
                'active_sessions': len(self.sessions),
                'cache_age_seconds': int(time.time() - self.cache_updated_at),
                'sessions': [
                    {
                        'session_id': sid,
                        'account_count': len(info['accounts']),
                        'created_at': info['created_at'],
                        'expires_at': info['expires_at']
                    }
                    for sid, info in self.sessions.items()
                ]
            }
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            raise

    async def cleanup_expired_sessions(self):
        """清理过期会话"""
        current_time = time.time()
        expired_sessions = []

        try:
            async with self.lock:
                for session_id, session_info in self.sessions.items():
                    if current_time > session_info['expires_at']:
                        expired_sessions.append(session_id)

            # 在锁外释放会话，避免长时间持锁
            for session_id in expired_sessions:
                await self.release_session(session_id)
                logger.info(f"清理过期会话: {session_id}")
        except Exception as e:
            logger.error(f"清理会话失败: {e}")
    
    async def update_account_credits(self, email: str, credits_data: Dict[str, Any]) -> bool:
        """更新账号credits信息到数据库"""
        try:
            async with aiosqlite.connect(self.db_path, timeout=config.DB_TIMEOUT) as db:
                await db.execute(
                    '''
                    UPDATE accounts 
                    SET request_limit = ?,
                        requests_used = ?,
                        requests_remaining = ?,
                        is_unlimited = ?,
                        quota_type = ?,
                        next_refresh_time = ?,
                        refresh_duration = ?,
                        credits_updated_at = ?
                    WHERE email = ?
                    ''',
                    (
                        credits_data.get('request_limit', 0),
                        credits_data.get('requests_used', 0),
                        credits_data.get('requests_remaining', 0),
                        1 if credits_data.get('is_unlimited') else 0,
                        credits_data.get('quota_type', 'normal'),
                        credits_data.get('next_refresh_time'),
                        credits_data.get('refresh_duration', 'WEEKLY'),
                        credits_data.get('updated_at'),
                        email
                    )
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"更新credits失败 {email}: {e}")
            return False
    
    async def refresh_credits(self, email: Optional[str] = None) -> Dict[str, Any]:
        """刷新账号credits"""
        try:
            async with aiosqlite.connect(self.db_path, timeout=config.DB_TIMEOUT) as db:
                db.row_factory = aiosqlite.Row
                
                if email:
                    # 刷新单个账号
                    cursor = await db.execute(
                        'SELECT email, id_token, refresh_token FROM accounts WHERE email = ? AND status = "active"',
                        (email,)
                    )
                    row = await cursor.fetchone()
                    accounts = [dict(row)] if row else []
                else:
                    # 刷新所有active账号
                    cursor = await db.execute(
                        'SELECT email, id_token, refresh_token FROM accounts WHERE status = "active"'
                    )
                    rows = await cursor.fetchall()
                    accounts = [dict(row) for row in rows]
                
                if not accounts:
                    return {"success": False, "message": "未找到账号"}
                
                results = []
                success_count = 0
                
                for account in accounts:
                    acc_email = account['email']
                    id_token = account['id_token']
                    refresh_token = account['refresh_token']
                    
                    logger.info(f"刷新credits: {acc_email}")
                    
                    # 先尝试用现有token获取credits
                    credits_data = await self.credits_service.get_credits(id_token)
                    
                    # 记录错误信息用于调试
                    if not credits_data['success']:
                        error_msg = credits_data.get('error', '')
                        logger.warning(f"⚠️ 第一次尝试失败 {acc_email}: {error_msg}")
                        
                        # 判断是否是认证错误（放宽匹配条件）
                        is_auth_error = any(keyword in error_msg for keyword in [
                            'Unauthorized', 'User not in context', 'Not found', 
                            'Authentication', 'Invalid token', 'Token expired'
                        ])
                        
                        if is_auth_error:
                            logger.info(f"🔄 检测到认证错误，尝试刷新Token: {acc_email}")
                            
                            # 刷新token
                            new_id_token = await self.credits_service.refresh_id_token(refresh_token)
                            
                            if new_id_token:
                                logger.info(f"✅ Token刷新成功，更新数据库: {acc_email}")
                                
                                # 更新数据库中的id_token
                                await db.execute(
                                    'UPDATE accounts SET id_token = ? WHERE email = ?',
                                    (new_id_token, acc_email)
                                )
                                await db.commit()
                                
                                # 用新token重试
                                logger.info(f"🔁 使用新Token重试获取Credits: {acc_email}")
                                credits_data = await self.credits_service.get_credits(new_id_token)
                                
                                if credits_data['success']:
                                    logger.info(f"🎉 重试成功: {acc_email}")
                                else:
                                    logger.error(f"❌ 重试仍然失败: {acc_email} - {credits_data.get('error')}")
                            else:
                                logger.error(f"❌ Token刷新失败: {acc_email}")
                                credits_data = {'success': False, 'error': '刷新Token失败'}
                        else:
                            logger.error(f"❌ 非认证错误，不刷新Token: {error_msg}")
                    
                    if credits_data['success']:
                        # 更新数据库
                        await self.update_account_credits(acc_email, credits_data)
                        success_count += 1
                        
                        results.append({
                            "email": acc_email,
                            "success": True,
                            "credits": {
                                "request_limit": credits_data['request_limit'],
                                "requests_remaining": credits_data['requests_remaining'],
                                "quota_type": credits_data['quota_type']
                            }
                        })
                    else:
                        results.append({
                            "email": acc_email,
                            "success": False,
                            "error": credits_data.get('error')
                        })
                    
                    # 避免请求过快
                    if len(accounts) > 1:
                        await asyncio.sleep(1)
                
                # 刷新缓存
                await self.refresh_account_cache()
                
                return {
                    "success": True,
                    "message": f"刷新完成: {success_count}/{len(accounts)}",
                    "total": len(accounts),
                    "success_count": success_count,
                    "results": results
                }
                
        except Exception as e:
            logger.error(f"刷新credits失败: {e}")
            return {"success": False, "message": str(e)}


# ==================== FastAPI应用 ====================
app = FastAPI(title="Warp账号池服务", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局管理器实例
pool_manager = None


@app.on_event("startup")
async def startup_event():
    """启动事件"""
    global pool_manager

    logger.info("账号池服务启动中...")

    # 初始化管理器
    pool_manager = AccountPoolManager()
    await pool_manager.init_async()

    logger.info("账号池服务已启动")

    # 启动定期任务
    async def periodic_tasks():
        credits_refresh_counter = 0  # credits刷新计数器
        
        while True:
            await asyncio.sleep(60)  # 每分钟执行一次
            try:
                # 清理过期会话
                await pool_manager.cleanup_expired_sessions()
                # 刷新缓存
                await pool_manager.refresh_account_cache()
                
                # 每30分钟刷新一次credits
                credits_refresh_counter += 1
                if credits_refresh_counter >= 30:
                    logger.info("开始定时刷新账号credits...")
                    asyncio.create_task(pool_manager.refresh_credits())  # 异步执行，不阻塞
                    credits_refresh_counter = 0
            except Exception as e:
                logger.error(f"定期任务执行失败: {e}")

    asyncio.create_task(periodic_tasks())


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Warp Account Pool",
        "version": "2.0.0",
        "status": "running",
        "optimized": True
    }


@app.post("/api/accounts/allocate")
async def allocate_accounts(request: AllocateRequest):
    """分配账号"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")

        result = await pool_manager.allocate_accounts(
            count=request.count,
            session_duration=request.session_duration
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分配账号失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/accounts/release")
async def release_accounts(request: ReleaseRequest):
    """释放账号"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")

        result = await pool_manager.release_session(request.session_id)
        return result
    except Exception as e:
        logger.error(f"释放账号失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/accounts/mark_blocked")
async def mark_account_blocked(request: BlockAccountRequest):
    """标记账号为已封禁"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")

        # 根据JWT token片段或email找到并标记账号
        result = await pool_manager.mark_account_blocked(
            jwt_token=request.jwt_token,
            email=request.email
        )

        if not result['success']:
            raise HTTPException(status_code=404, detail=result['message'])

        return result
    except HTTPException as e:
        logger.error(f"标记账号失败: {e}")
        raise
    except Exception as e:
        logger.error(f"标记账号失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status")
async def get_status():
    """获取池状态"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")

        status = await pool_manager.get_pool_status()
        return status
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/accounts/list")
async def list_accounts(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """获取账号列表
    
    Args:
        status: 账号状态过滤 (active/blocked/all)
        limit: 每页数量
        offset: 偏移量
    """
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")
        
        async with aiosqlite.connect(pool_manager.db_path, timeout=config.DB_TIMEOUT) as db:
            db.row_factory = aiosqlite.Row
            
            # 构建查询
            where_clause = ""
            if status and status != "all":
                where_clause = f"WHERE status = '{status}'"
            
            # 查询总数
            count_query = f"SELECT COUNT(*) as total FROM accounts {where_clause}"
            cursor = await db.execute(count_query)
            row = await cursor.fetchone()
            total = row['total'] if row else 0
            
            # 查询账号列表
            query = f"""
                SELECT 
                    email,
                    local_id,
                    status,
                    last_used,
                    created_at,
                    proxy_info,
                    user_agent,
                    request_limit,
                    requests_used,
                    requests_remaining,
                    is_unlimited,
                    quota_type,
                    next_refresh_time,
                    refresh_duration,
                    credits_updated_at
                FROM accounts
                {where_clause}
                ORDER BY created_at DESC
                LIMIT {limit} OFFSET {offset}
            """
            
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            
            accounts = []
            for row in rows:
                account = dict(row)
                # 检查是否被锁定
                is_locked = account['email'] in pool_manager.locked_accounts
                account['is_locked'] = is_locked
                if is_locked:
                    account['locked_by_session'] = pool_manager.locked_accounts[account['email']]
                
                accounts.append(account)
            
            return {
                "success": True,
                "total": total,
                "limit": limit,
                "offset": offset,
                "accounts": accounts
            }
            
    except Exception as e:
        logger.error(f"获取账号列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_enabled": True,
        "optimized": True
    }


@app.post("/api/accounts/refresh_credits")
async def refresh_credits(request: RefreshCreditsRequest):
    """刷新账号credits"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")
        
        result = await pool_manager.refresh_credits(email=request.email)
        
        if not result['success']:
            raise HTTPException(status_code=400, detail=result.get('message', 'Failed to refresh credits'))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新credits失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/accounts/add_from_link")
async def add_account_from_link(request: AddAccountFromLinkRequest):
    """从登录链接智能添加账号（支持邮箱链接和客户端重定向链接）"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")
        
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(request.login_link)
        query_params = parse_qs(parsed_url.query)
        
        # 判断链接类型
        local_id = None
        id_token = None
        refresh_token = None
        
        # 方式1: 客户端重定向链接 (warp://auth/desktop_redirect)
        if parsed_url.scheme == 'warp' and 'refresh_token' in query_params:
            logger.info(f"🔗 检测到客户端重定向链接")
            
            refresh_token = query_params.get('refresh_token', [None])[0]
            user_uid = query_params.get('user_uid', [None])[0]
            
            if not refresh_token:
                raise HTTPException(status_code=400, detail="Invalid client link: refresh_token not found")
            
            logger.info(f"✅ 提取refresh_token成功: {refresh_token[:30]}...")
            logger.info(f"✅ 提取user_uid: {user_uid}")
            
            # 使用refresh_token换取id_token
            logger.info("🔄 使用refresh_token获取id_token...")
            new_id_token = await pool_manager.credits_service.refresh_id_token(refresh_token)
            
            if not new_id_token:
                raise HTTPException(status_code=400, detail="Failed to get id_token from refresh_token")
            
            id_token = new_id_token
            local_id = user_uid  # user_uid就是local_id
            logger.info(f"✅ 获取id_token成功: {id_token[:30]}...")
        
        # 方式2: 邮箱链接 (包含oobCode)
        elif 'oobCode' in query_params:
            logger.info(f"📧 检测到邮箱登录链接")
            
            oob_code = query_params.get('oobCode', [None])[0]
            if not oob_code:
                raise HTTPException(status_code=400, detail="Invalid login link: oobCode not found")
            
            logger.info(f"解析oobCode成功: {oob_code[:20]}...")
            
            # 调用Firebase signInWithEmailLink API
            firebase_api_key = config.FIREBASE_API_KEY
            signin_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink?key={firebase_api_key}"
            
            payload = {
                "email": request.email,
                "oobCode": oob_code
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(signin_url, json=payload)
                
                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"Firebase登录失败: {error_detail}")
                    raise HTTPException(status_code=400, detail=f"Firebase login failed: {error_detail}")
                
                firebase_data = response.json()
                logger.info(f"✅ Firebase登录成功: {request.email}")
            
            # 提取参数
            local_id = firebase_data.get('localId')
            id_token = firebase_data.get('idToken')
            refresh_token = firebase_data.get('refreshToken')
        
        else:
            raise HTTPException(
                status_code=400, 
                detail="Invalid link format. Please provide either email login link or warp:// client redirect link"
            )
        
        # 验证必需参数
        if not all([local_id, id_token, refresh_token]):
            raise HTTPException(status_code=500, detail="Missing required authentication fields")
        
        # 4. 添加到数据库
        async with aiosqlite.connect(pool_manager.db_path, timeout=config.DB_TIMEOUT) as db:
            try:
                await db.execute(
                    '''
                    INSERT INTO accounts
                    (email, local_id, id_token, refresh_token, status, created_at, last_used)
                    VALUES (?, ?, ?, ?, 'active', ?, NULL)
                    ''',
                    (request.email, local_id, id_token, refresh_token, datetime.now().isoformat())
                )
                await db.commit()
                
                logger.info(f"✅ 账号已添加: {request.email}")
                
                # 刷新缓存
                await pool_manager.refresh_account_cache()
                
                return {
                    "success": True,
                    "message": f"Account {request.email} added successfully",
                    "account": {
                        "email": request.email,
                        "local_id": local_id,
                        "status": "active"
                    }
                }
                
            except aiosqlite.IntegrityError:
                raise HTTPException(status_code=400, detail=f"Account {request.email} already exists")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加账号失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 主函数 ====================
async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("Warp账号池HTTP服务 v2.0 (优化版)")
    logger.info(f"端口: {config.POOL_SERVICE_PORT}")
    logger.info(f"数据库: {config.DATABASE_PATH}")
    logger.info("=" * 60)

    # 检查数据库
    import os
    if not os.path.exists(config.DATABASE_PATH):
        logger.error(f"数据库文件不存在: {config.DATABASE_PATH}")
        logger.error("请先运行注册脚本创建账号")
        return

    # 启动服务
    server_config = uvicorn.Config(
        app=app,
        host=config.POOL_SERVICE_HOST,
        port=config.POOL_SERVICE_PORT,
        log_level=config.LOG_LEVEL.lower()
    )
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
