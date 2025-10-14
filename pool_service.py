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
    login_link: str

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
                                                 created_at
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
        while True:
            await asyncio.sleep(60)  # 每分钟执行一次
            try:
                # 清理过期会话
                await pool_manager.cleanup_expired_sessions()
                # 刷新缓存
                await pool_manager.refresh_account_cache()
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
                    user_agent
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


@app.post("/api/accounts/add_from_link")
async def add_account_from_link(request: AddAccountFromLinkRequest):
    """从登录链接智能添加账号"""
    try:
        if not pool_manager:
            raise HTTPException(status_code=503, detail="Service initializing")
        
        # 1. 解析登录链接获取oobCode
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(request.login_link)
        query_params = parse_qs(parsed_url.query)
        
        oob_code = query_params.get('oobCode', [None])[0]
        if not oob_code:
            raise HTTPException(status_code=400, detail="Invalid login link: oobCode not found")
        
        logger.info(f"解析oobCode成功: {oob_code[:20]}...")
        
        # 2. 调用Firebase signInWithEmailLink API
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
        
        # 3. 提取需要的参数
        local_id = firebase_data.get('localId')
        id_token = firebase_data.get('idToken')
        refresh_token = firebase_data.get('refreshToken')
        
        if not all([local_id, id_token, refresh_token]):
            raise HTTPException(status_code=500, detail="Firebase response missing required fields")
        
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
