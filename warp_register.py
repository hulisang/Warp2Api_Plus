#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp账号注册脚本
使用Outlook邮箱API和动态IP代理进行账号注册
"""

import asyncio
import copy
import email as email_lib
import html
import imaplib
import logging
import random
import re
import secrets
import ssl
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import aiosqlite
import httpx
from fake_useragent import UserAgent

# ==================== 配置部分 ====================
import config

# 日志配置
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# User Agent生成器
ua = UserAgent()


# ==================== Outlook API客户端 ====================
class OutlookAPIClient:
    """Outlook API客户端"""

    def __init__(self, app_id: str, app_key: str):
        self.app_id = app_id
        self.app_key = app_key
        self.base_url = config.OUTLOOK_BASE_URL
        self.client = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_client(self):
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={
                    'User-Agent': ua.random
                }
            )

    async def close(self):
        if self.client and not self.client.is_closed:
            await self.client.aclose()
            self.client = None

    async def get_email(self, commodity_id: int, num: int) -> Dict[str, Any]:
        """提取邮箱"""
        await self._ensure_client()

        url = f"{self.base_url}/getEmail.php"
        params = {
            'app_id': self.app_id,
            'app_key': self.app_key,
            'commodity_id': commodity_id,
            'num': num
        }

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            result = response.json()
            return result
        except Exception as e:
            logger.error(f"获取邮箱失败: {e}")
            return {"code": 500, "message": str(e), "data": None}


# ==================== 异步代理管理器 ====================
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
        return config.PROXY_URL

    def format_proxy_for_httpx(self, proxy_str: str) -> Optional[str]:
        """格式化代理为httpx格式"""
        if not proxy_str:
            return None

        try:
            if '@' in proxy_str:
                credentials, host_port = proxy_str.split('@')
                user, password = credentials.split(':')
                host, port = host_port.split(':')
                # httpx使用socks5代理格式
                return f"socks5://{user}:{password}@{host}:{port}"
            else:
                host, port = proxy_str.split(':')
                return f"socks5://{host}:{port}"
        except Exception as e:
            logger.error(f"格式化代理失败: {e}")
            return None


# ==================== 异步数据库管理 ====================
class AsyncDatabaseManager:
    """异步数据库管理器"""

    def __init__(self, db_path=config.DATABASE_PATH):
        self.db_path = db_path

    async def add_account(self, email, local_id, id_token, refresh_token,
                          email_password=None, client_id=None, outlook_refresh_token=None,
                          status='active', proxy_info=None, user_agent=None):
        """添加账号"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                                 INSERT INTO accounts
                                 (email, email_password, local_id, id_token, refresh_token,
                                  client_id, outlook_refresh_token, status, proxy_info, user_agent)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                 ''', (email, email_password, local_id, id_token, refresh_token,
                                       client_id, outlook_refresh_token, status, proxy_info, user_agent))

                await db.commit()
                logger.info(f"✅ 账号已保存: {email}")
                return True
        except aiosqlite.IntegrityError:
            logger.warning(f"账号已存在: {email}")
            return False
        except Exception as e:
            logger.error(f"保存账号失败: {e}")
            return False

    async def get_account_count(self, status='active'):
        """获取账号数量"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT COUNT(*) FROM accounts WHERE status = ?', (status,))
            row = await cursor.fetchone()
            return row[0] if row else 0


# ==================== Warp注册机器人 ====================
class WarpRegistrationBot:
    """Warp注册机器人"""

    def __init__(self, db_manager: AsyncDatabaseManager, proxy_manager: AsyncProxyManager):
        self.db_manager = db_manager
        self.proxy_manager = proxy_manager
        self.firebase_api_keys = config.FIREBASE_API_KEYS
        self.current_api_key_index = 0
        self.user_agent = ua.random  # 每个机器人实例一个UA
        self.async_client = None

    def get_next_api_key(self) -> str:
        """获取下一个Firebase API密钥"""
        key = self.firebase_api_keys[self.current_api_key_index]
        self.current_api_key_index = (self.current_api_key_index + 1) % len(self.firebase_api_keys)
        return key

    async def send_email_signin_request(self, email: str, proxy: str = None) -> Dict[str, Any]:
        """发送邮箱登录请求"""
        api_key = self.get_next_api_key()
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"

        payload = {
            "requestType": "EMAIL_SIGNIN",
            "email": email,
            "clientType": "CLIENT_TYPE_WEB",
            "continueUrl": "https://app.warp.dev/login",
            "canHandleCodeInApp": True
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        }

        async with httpx.AsyncClient(
                proxy=proxy,
                verify=False,
                timeout=httpx.Timeout(30.0),
                headers=headers
        ) as client:
            try:
                response = await client.post(url, json=payload)

                if response.status_code == 200:
                    logger.info(f"✅ 发送登录请求成功: {email}")
                    return {
                        "success": True,
                        "response": response.json()
                    }
                else:
                    logger.error(f"发送登录请求失败: {response.status_code}")
                    return {
                        "success": False,
                        "error": response.text
                    }
            except (httpx.ProxyError, ssl.SSLError) as e:
                logger.error(f"代理错误: {e}")
                return {
                    "success": False,
                    "error": "proxy_error"
                }
            except Exception as e:
                logger.error(f"发送登录请求异常: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }

    async def get_new_access_token(self, refresh_token: str, client_id: str) -> Optional[str]:
        """刷新OAuth2访问令牌"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    data={
                        'grant_type': 'refresh_token',
                        'refresh_token': refresh_token,
                        'client_id': client_id,
                        'scope': 'https://graph.microsoft.com/.default'  # 添加Graph API scope
                    }
                )

                if response.status_code == 200:
                    return response.json().get('access_token')
        except Exception as e:
            logger.error(f"刷新token失败: {e}")

        return None

    async def wait_for_verification_email(self, access_token: str, email: str,
                                          client_id: str, refresh_token: str,
                                          timeout: int = 30) -> Optional[Dict[str, Any]]:
        """等待Warp验证邮件（使用Microsoft Graph API）"""
        logger.info(f"📬 等待验证邮件 (超时: {timeout}秒)...")
        await asyncio.sleep(3)

        start_time = time.time()
        check_count = 0

        while time.time() - start_time < timeout:
            check_count += 1
            logger.info(f"  第 {check_count} 次检查...")

            try:
                result = await self._check_email_graph(access_token)

                if result:
                    return result

            except Exception as e:
                logger.warning(f"检查邮件时出错: {e}")
                # 如果是认证错误，尝试刷新token
                if "401" in str(e) or "Unauthorized" in str(e):
                    new_token = await self.get_new_access_token(refresh_token, client_id)
                    if new_token:
                        access_token = new_token
                        logger.info("access_token已刷新")

            await asyncio.sleep(5)

        logger.error("❌ 等待验证邮件超时")
        return None

    async def _check_email_graph(self, access_token: str) -> Optional[Dict[str, Any]]:
        """使用Graph API检查邮件（简化查询，避免InefficientFilter错误）"""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Prefer': 'outlook.body-content-type="html"'
            }

            # 简化过滤条件，移除$orderby
            filter_conditions = [
                "contains(subject, 'Warp')",
            ]

            async with httpx.AsyncClient(timeout=30) as client:
                async def check_folder(endpoint_url: str) -> Optional[Dict[str, Any]]:
                    for condition in filter_conditions:
                        try:
                            response = await client.get(
                                endpoint_url,
                                headers=headers,
                                params={
                                    '$filter': condition,
                                    '$top': 10,  # 获取更多邮件以补偿无排序
                                    # 移除 '$orderby': 'receivedDateTime desc',
                                    '$select': 'id,subject,from,body,receivedDateTime'
                                }
                            )

                            if response.status_code == 401:
                                raise Exception("Unauthorized")

                            if response.status_code == 200:
                                data = response.json()
                                messages = data.get('value', [])

                                # 在客户端按接收时间排序
                                messages.sort(
                                    key=lambda x: x.get('receivedDateTime', ''),
                                    reverse=True
                                )

                                # 只检查最新的3封
                                for message in messages[:3]:
                                    body_content = message.get('body', {}).get('content', '')
                                    verification_data = self._extract_verification_link(body_content)
                                    if verification_data:
                                        logger.info(f"✅ 使用条件 '{condition}' 找到验证邮件")
                                        return verification_data
                            else:
                                logger.warning(
                                    f"条件 '{condition}' 查询失败，状态码: {response.status_code}, 响应: {response.text}")

                        except Exception as e:
                            logger.warning(f"在检查条件 '{condition}' 时出错: {e}")
                            if "Unauthorized" in str(e):
                                raise
                            continue
                    return None

                # 检查收件箱
                logger.info("  正在检查收件箱...")
                inbox_url = "https://graph.microsoft.com/v1.0/me/messages"
                result = await check_folder(inbox_url)
                if result:
                    return result

                # 检查垃圾邮件
                logger.info("  正在检查垃圾邮件文件夹...")
                try:
                    folder_response = await client.get(
                        "https://graph.microsoft.com/v1.0/me/mailFolders",
                        headers=headers,
                        params={'$filter': "displayName eq 'Junk Email'"}
                    )
                    if folder_response.status_code == 200:
                        folders = folder_response.json().get('value', [])
                        if folders:
                            junk_folder_id = folders[0]['id']
                            junk_url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{junk_folder_id}/messages"
                            result = await check_folder(junk_url)
                            if result:
                                return result
                except Exception as e:
                    logger.warning(f"检查垃圾邮件文件夹出错: {e}")

        except Exception as e:
            logger.error(f"Graph API邮件检查失败: {e}")
            if "Unauthorized" in str(e):
                raise

        return None

    def _extract_verification_link(self, body_content: str) -> Optional[Dict[str, Any]]:
        """从邮件内容中提取验证链接"""
        link_patterns = [
            r'href=["\'](https://[^"\']*firebaseapp\.com[^"\']*)["\']',
            r'(https://astral-field[^"\'\s<>]+)',
            r'https://[^"\'\s<>]*__/auth/action[^"\'\s<>]*',
            r'(https://[^\s<>]+\?.*oobCode=[^"\'\s<>]+)'
        ]

        for pattern in link_patterns:
            matches = re.findall(pattern, body_content, re.IGNORECASE)
            if matches:
                verification_link = html.unescape(matches[0])
                verification_link = verification_link.replace('&amp;', '&')

                parsed = urlparse(verification_link)
                params = parse_qs(parsed.query)

                oob_code = params.get('oobCode', [None])[0]
                if oob_code:
                    return {
                        "oob_code": oob_code,
                        "verification_link": verification_link
                    }

        return None

    def _check_email_sync(self, access_token: str, email: str) -> Optional[Dict[str, Any]]:
        """同步检查邮件（在executor中运行）"""
        try:
            mail = imaplib.IMAP4_SSL('outlook.office365.com')
            auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
            mail.authenticate('XOAUTH2', lambda x: auth_string)

            for folder in ["INBOX", "Junk"]:  # 优先检查INBOX
                try:
                    mail.select(folder)

                    search_criteria = [
                        '(FROM "noreply@warp.dev")',
                        '(FROM "noreply@firebase.com")',
                        '(SUBJECT "Sign in")',
                        '(SUBJECT "Warp")',
                        '(SUBJECT "verify")'
                    ]

                    for criteria in search_criteria:
                        try:
                            status, message_ids = mail.search(None, criteria)

                            if status == 'OK' and message_ids[0]:
                                email_ids = message_ids[0].split()

                                # 检查最新的几封邮件
                                for message_id in reversed(email_ids[-3:]):  # 只检查最新的3封
                                    status, msg_data = mail.fetch(message_id, '(RFC822)')

                                    if status != 'OK':
                                        continue

                                    for response_part in msg_data:
                                        if isinstance(response_part, tuple):
                                            msg = email_lib.message_from_bytes(response_part[1])

                                            # 改进的邮件内容提取
                                            body = self._extract_email_body(msg)

                                            # 改进的链接提取模式
                                            link_patterns = [
                                                r'href=["\'](https://[^"\']*firebaseapp\.com[^"\']*)["\']',
                                                r'(https://astral-field[^"\'\s<>]+)',  # 直接匹配您的特定域名
                                                r'https://[^"\'\s<>]*__/auth/action[^"\'\s<>]*'
                                            ]

                                            for pattern in link_patterns:
                                                matches = re.findall(pattern, body, re.IGNORECASE)
                                                if matches:
                                                    # 清理链接
                                                    verification_link = html.unescape(matches[0])
                                                    verification_link = verification_link.replace('&amp;', '&')

                                                    # 解析参数
                                                    parsed = urlparse(verification_link)
                                                    params = parse_qs(parsed.query)

                                                    oob_code = params.get('oobCode', [None])[0]
                                                    if oob_code:
                                                        mail.logout()
                                                        logger.info(f"✅ 找到验证码: {oob_code}")
                                                        return {
                                                            "oob_code": oob_code,
                                                            "verification_link": verification_link
                                                        }

                        except Exception as e:
                            logger.warning(f"搜索条件 '{criteria}' 出错: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"处理文件夹 {folder} 出错: {e}")
                    continue

            mail.logout()

        except Exception as e:
            logger.error(f"邮件检查失败: {e}")

        return None

    def _extract_email_body(self, msg):
        """提取邮件正文内容（处理多部分邮件）"""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # 跳过附件
                if "attachment" in content_disposition:
                    continue

                if content_type in ["text/plain", "text/html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode('utf-8', errors='ignore')
                    except Exception as e:
                        logger.debug(f"解析邮件部分出错: {e}")
        else:
            # 单部分邮件
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode('utf-8', errors='ignore')
            except Exception as e:
                logger.debug(f"解析单部分邮件出错: {e}")

        return body

    def extract_and_recombine_url(self, original_url):
        """
        从原始URL中提取参数并重新组合成目标格式

        Args:
            original_url (str): 原始URL字符串

        Returns:
            str: 重新组合后的URL
        """
        # 解析URL
        parsed = urlparse(original_url)

        # 提取查询参数
        query_params = parse_qs(parsed.query)

        # 提取需要的参数，注意parse_qs返回的是列表，我们取第一个值
        api_key = query_params.get('apiKey', [''])[0]
        mode = query_params.get('mode', [''])[0]
        oob_code = query_params.get('oobCode', [''])[0]
        lang = query_params.get('lang', [''])[0]

        # 从continueUrl中提取基础路径
        continue_url = query_params.get('continueUrl', [''])[0]
        if continue_url:
            # 解析continueUrl获取基础路径
            continue_parsed = urlparse(continue_url)
            base_path = continue_parsed.path
        else:
            base_path = '/login'  # 默认路径

        # 构建新的查询参数
        new_params = {
            'apiKey': api_key,
            'oobCode': oob_code,
            'mode': mode,
            'lang': lang
        }

        # 构建新的URL
        new_url = urlunparse((
            'https',  # scheme
            'app.warp.dev',  # netloc
            base_path,  # path
            '',  # params
            urlencode(new_params),  # query
            ''  # fragment
        ))

        return new_url

    async def complete_email_signin(self, email: str, oob_code: str) -> Dict[str, Any]:
        """完成邮箱登录"""
        api_key = self.get_next_api_key()
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink?key={api_key}"

        payload = {
            "email": email,
            "oobCode": oob_code
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Accept": "*/*"
        }

        try:
            response = await self.async_client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ 登录成功 [{email}]: {data}")
                return {
                    "success": True,
                    "id_token": data.get("idToken"),
                    "refresh_token": data.get("refreshToken"),
                    "local_id": data.get("localId"),
                    "email": data.get("email")
                }
            else:
                logger.error(f"登录失败: {response.status_code}")
                return {
                    "success": False,
                    "error": response.text
                }
        except (httpx.ProxyError, ssl.SSLError) as e:
            logger.error(f"代理错误: {e}")
            return {
                "success": False,
                "error": "proxy_error"
            }
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def activate_warp_user(self, id_token: str, session_id: str) -> Dict[str, Any]:
        """激活Warp用户"""
        url = "https://app.warp.dev/graphql/v2"

        query = """mutation GetOrCreateUser($input: GetOrCreateUserInput!, $requestContext: RequestContext!) {\n  getOrCreateUser(requestContext: $requestContext, input: $input) {\n    __typename\n    ... on GetOrCreateUserOutput {\n      uid\n      isOnboarded\n      anonymousUserInfo {\n        anonymousUserType\n        linkedAt\n        __typename\n      }\n      workspaces {\n        joinableTeams {\n          teamUid\n          numMembers\n          name\n          teamAcceptingInvites\n          __typename\n        }\n        __typename\n      }\n      onboardingSurveyStatus\n      firstLoginAt\n      adminOf\n      deletedAnonymousUser\n      __typename\n    }\n    ... on UserFacingError {\n      error {\n        __typename\n        message\n        ... on TOSViolationError {\n          message\n          __typename\n        }\n      }\n      __typename\n    }\n  }\n}\n"""

        data = {
            "operationName": "GetOrCreateUser",
            "variables": {
                "input": {
                    "sessionId": session_id,
                },
                "requestContext": {
                    "clientContext": {},
                    "osContext": {},
                }
            },
            "query": query
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {id_token}",
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "referer": "https://app.warp.dev/login"
        }
        # print(f"cookies: {self.async_client.cookies}")  # Debug log

        try:
            response = await self.async_client.post(
                url,
                params={"op": "GetOrCreateUser"},
                json=data,
                headers=headers
            )
            print(f"[{response.status_code}] Activate Warp Response: {response.text}")  # Debug log

            if response.status_code == 200:
                result = response.json()
                user_data = result.get("data", {}).get("getOrCreateUser", {})

                if user_data.get("__typename") == "GetOrCreateUserOutput":
                    uid = user_data.get("uid")
                    logger.info(f"✅ Warp用户激活成功: UID={uid}")

                    response = await self.async_client.post(
                        url,
                        params={"op": "UpdateOnboardingSurveyStatus"},
                        json={
                            "operationName": "UpdateOnboardingSurveyStatus",
                            "variables": {
                                "input": {"status":"SKIPPED"},
                                "requestContext": {"osContext":{},"clientContext":{}}
                            },
                            "query": "mutation UpdateOnboardingSurveyStatus($input: UpdateOnboardingSurveyStatusInput!, $requestContext: RequestContext!) {\n  updateOnboardingSurveyStatus(input: $input, requestContext: $requestContext) {\n    __typename\n    ... on UpdateOnboardingSurveyStatusOutput {\n      status\n      responseContext {\n        __typename\n      }\n      __typename\n    }\n    ... on UserFacingError {\n      error {\n        message\n        __typename\n      }\n      __typename\n    }\n  }\n}\n"
                        },
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {id_token}",
                            "User-Agent": self.user_agent,
                            "Accept": "*/*",
                        }
                    )
                    print(f"Update Onboarding Survey Status Response: {response.text}")  # Debug log

                    return {
                        "success": True,
                        "uid": uid
                    }

            return {"success": False, "error": "激活失败"}

        except (httpx.ProxyError, ssl.SSLError) as e:
            logger.error(f"代理错误: {e}")
            return {"success": False, "error": "proxy_error"}
        except Exception as e:
            logger.error(f"激活Warp用户失败: {e}")
            return {"success": False, "error": str(e)}

    async def _generate_worker_payload(self, session_id: str) -> Dict[str, Any]:
        """
        生成worker请求的payload数据 - 完整的、稳定的版本
        所有字段都包含在内，没有任何省略
        """

        # 扩展的基础配置文件 - 包含更多真实捕获的配置
        BASE_PROFILES_EXTENDED = [
            {
                "profile_name": "Win10_Chrome_NVIDIA_GTX1660Ti",
                "os": "Windows",
                "os_version": "10.0.0",
                "platform": "Win32",
                "architecture": "x86",
                "bitness": 64,
                "vendor": "Google Inc.",
                "gpu_vendor_string": "Google Inc. (NVIDIA)",
                "gpu_renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti (0x00002182) Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "screen_resolution": {"width": 1707, "height": 960},
                "hardware_config": {"memory": 8, "cores": 12},
                "hashes": {
                    "prototype_hash": "5051906984991708",
                    "math_hash": "4407615957639726",
                    "offline_audio_hash": "733027540168168",
                    "mime_types_hash": "6633968372405724",
                    "errors_hash": "1415081268456649"
                }
            },
            {
                "profile_name": "Win10_Chrome_AMD_Radeon",
                "os": "Windows",
                "os_version": "10.0.0",
                "platform": "Win32",
                "architecture": "x86",
                "bitness": 64,
                "vendor": "Google Inc.",
                "gpu_vendor_string": "Google Inc. (AMD)",
                "gpu_renderer": "ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "screen_resolution": {"width": 1536, "height": 864},
                "hardware_config": {"memory": 8, "cores": 16},
                "hashes": {
                    "prototype_hash": "4842229194603551",
                    "math_hash": "4407615957639726",
                    "offline_audio_hash": "733027540168168",
                    "mime_types_hash": "2795763505992044",
                    "errors_hash": "1415081268456649"
                }
            },
            {
                "profile_name": "Win10_Chrome_NVIDIA_RTX3060",
                "os": "Windows",
                "os_version": "10.0.0",
                "platform": "Win32",
                "architecture": "x86",
                "bitness": 64,
                "vendor": "Google Inc.",
                "gpu_vendor_string": "Google Inc. (NVIDIA)",
                "gpu_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "screen_resolution": {"width": 1920, "height": 1080},
                "hardware_config": {"memory": 16, "cores": 8},
                "hashes": {
                    "prototype_hash": "5051906984991708",
                    "math_hash": "4407615957639726",
                    "offline_audio_hash": "733027540168168",
                    "mime_types_hash": "6633968372405724",
                    "errors_hash": "1415081268456649"
                }
            }
        ]

        # Chrome/Edge 版本配置 - 完整版本信息
        BROWSER_VERSIONS_COMPLETE = [
            {
                "browser": "Chrome",
                "major": 140,
                "full_version": "140.0.7339.208",
                "brands": [
                    {"brand": "Chromium", "version": "140"},
                    {"brand": "Not=A?Brand", "version": "24"},
                    {"brand": "Google Chrome", "version": "140"}
                ]
            },
            {
                "browser": "Edge",
                "major": 141,
                "full_version": "141.0.3537.57",
                "full_chromium_version": "141.0.7390.55",
                "brands": [
                    {"brand": "Microsoft Edge", "version": "141"},
                    {"brand": "Not?A_Brand", "version": "8"},
                    {"brand": "Chromium", "version": "141"}
                ]
            },
            {
                "browser": "Chrome",
                "major": 128,
                "full_version": "128.0.6613.137",
                "brands": [
                    {"brand": "Chromium", "version": "128"},
                    {"brand": "Not-A.Brand", "version": "24"},
                    {"brand": "Google Chrome", "version": "128"}
                ]
            },
            {
                "browser": "Chrome",
                "major": 126,
                "full_version": "126.0.6478.126",
                "brands": [
                    {"brand": "Chromium", "version": "126"},
                    {"brand": "Not-A.Brand", "version": "24"},
                    {"brand": "Google Chrome", "version": "126"}
                ]
            }
        ]

        # 语言配置
        LANGUAGE_CONFIGS_FIXED = [
            {"lang": "zh-CN", "languages": ["zh-CN", "zh"], "timezone_offset": 8, "timezone": "Asia/Shanghai"},
            {"lang": "zh-CN", "languages": ["zh-CN", "zh", "en"], "timezone_offset": 8, "timezone": "Asia/Shanghai"},
            {"lang": "zh-CN", "languages": ["zh-CN"], "timezone_offset": 8, "timezone": "Asia/Shanghai"},
            {"lang": "en-US", "languages": ["en-US", "en"], "timezone_offset": -5, "timezone": "America/New_York"},
            {"lang": "en-US", "languages": ["en-US", "en"], "timezone_offset": -7, "timezone": "America/Los_Angeles"}
        ]

        # 加载基础 window_keys 模板
        base_window_keys = [
            "Object",
            "Function",
            "Array",
            "Number",
            "parseFloat",
            "parseInt",
            "Infinity",
            "NaN",
            "undefined",
            "Boolean",
            "String",
            "Symbol",
            "Date",
            "Promise",
            "RegExp",
            "Error",
            "AggregateError",
            "EvalError",
            "RangeError",
            "ReferenceError",
            "SyntaxError",
            "TypeError",
            "URIError",
            "globalThis",
            "JSON",
            "Math",
            "Intl",
            "ArrayBuffer",
            "Atomics",
            "Uint8Array",
            "Int8Array",
            "Uint16Array",
            "Int16Array",
            "Uint32Array",
            "Int32Array",
            "BigUint64Array",
            "BigInt64Array",
            "Uint8ClampedArray",
            "Float32Array",
            "Float64Array",
            "DataView",
            "Map",
            "BigInt",
            "Set",
            "Iterator",
            "WeakMap",
            "WeakSet",
            "Proxy",
            "Reflect",
            "FinalizationRegistry",
            "WeakRef",
            "decodeURI",
            "decodeURIComponent",
            "encodeURI",
            "encodeURIComponent",
            "escape",
            "unescape",
            "eval",
            "isFinite",
            "isNaN",
            "console",
            "Option",
            "Image",
            "Audio",
            "webkitURL",
            "webkitRTCPeerConnection",
            "webkitMediaStream",
            "WebKitMutationObserver",
            "WebKitCSSMatrix",
            "XSLTProcessor",
            "XPathResult",
            "XPathExpression",
            "XPathEvaluator",
            "XMLSerializer",
            "XMLHttpRequestUpload",
            "XMLHttpRequestEventTarget",
            "XMLHttpRequest",
            "XMLDocument",
            "WritableStreamDefaultWriter",
            "WritableStreamDefaultController",
            "WritableStream",
            "Worker",
            "WindowControlsOverlayGeometryChangeEvent",
            "WindowControlsOverlay",
            "Window",
            "WheelEvent",
            "WebSocket",
            "WebGLVertexArrayObject",
            "WebGLUniformLocation",
            "WebGLTransformFeedback",
            "WebGLTexture",
            "WebGLSync",
            "WebGLShaderPrecisionFormat",
            "WebGLShader",
            "WebGLSampler",
            "WebGLRenderingContext",
            "WebGLRenderbuffer",
            "WebGLQuery",
            "WebGLProgram",
            "WebGLObject",
            "WebGLFramebuffer",
            "WebGLContextEvent",
            "WebGLBuffer",
            "WebGLActiveInfo",
            "WebGL2RenderingContext",
            "WaveShaperNode",
            "VisualViewport",
            "VisibilityStateEntry",
            "VirtualKeyboardGeometryChangeEvent",
            "ViewTransitionTypeSet",
            "ViewTransition",
            "ViewTimeline",
            "VideoPlaybackQuality",
            "VideoFrame",
            "VideoColorSpace",
            "ValidityState",
            "VTTCue",
            "UserActivation",
            "URLSearchParams",
            "URLPattern",
            "URL",
            "UIEvent",
            "TrustedTypePolicyFactory",
            "TrustedTypePolicy",
            "TrustedScriptURL",
            "TrustedScript",
            "TrustedHTML",
            "TreeWalker",
            "TransitionEvent",
            "TransformStreamDefaultController",
            "TransformStream",
            "TrackEvent",
            "TouchList",
            "TouchEvent",
            "Touch",
            "ToggleEvent",
            "TimeRanges",
            "TextUpdateEvent",
            "TextTrackList",
            "TextTrackCueList",
            "TextTrackCue",
            "TextTrack",
            "TextMetrics",
            "TextFormatUpdateEvent",
            "TextFormat",
            "TextEvent",
            "TextEncoderStream",
            "TextEncoder",
            "TextDecoderStream",
            "TextDecoder",
            "Text",
            "TaskSignal",
            "TaskPriorityChangeEvent",
            "TaskController",
            "TaskAttributionTiming",
            "SyncManager",
            "Subscriber",
            "SubmitEvent",
            "StyleSheetList",
            "StyleSheet",
            "StylePropertyMapReadOnly",
            "StylePropertyMap",
            "StorageEvent",
            "Storage",
            "StereoPannerNode",
            "StaticRange",
            "SourceBufferList",
            "SourceBuffer",
            "ShadowRoot",
            "Selection",
            "SecurityPolicyViolationEvent",
            "ScrollTimeline",
            "ScriptProcessorNode",
            "ScreenOrientation",
            "Screen",
            "Scheduling",
            "Scheduler",
            "SVGViewElement",
            "SVGUseElement",
            "SVGUnitTypes",
            "SVGTransformList",
            "SVGTransform",
            "SVGTitleElement",
            "SVGTextPositioningElement",
            "SVGTextPathElement",
            "SVGTextElement",
            "SVGTextContentElement",
            "SVGTSpanElement",
            "SVGSymbolElement",
            "SVGSwitchElement",
            "SVGStyleElement",
            "SVGStringList",
            "SVGStopElement",
            "SVGSetElement",
            "SVGScriptElement",
            "SVGSVGElement",
            "SVGRectElement",
            "SVGRect",
            "SVGRadialGradientElement",
            "SVGPreserveAspectRatio",
            "SVGPolylineElement",
            "SVGPolygonElement",
            "SVGPointList",
            "SVGPoint",
            "SVGPatternElement",
            "SVGPathElement",
            "SVGNumberList",
            "SVGNumber",
            "SVGMetadataElement",
            "SVGMatrix",
            "SVGMaskElement",
            "SVGMarkerElement",
            "SVGMPathElement",
            "SVGLinearGradientElement",
            "SVGLineElement",
            "SVGLengthList",
            "SVGLength",
            "SVGImageElement",
            "SVGGraphicsElement",
            "SVGGradientElement",
            "SVGGeometryElement",
            "SVGGElement",
            "SVGForeignObjectElement",
            "SVGFilterElement",
            "SVGFETurbulenceElement",
            "SVGFETileElement",
            "SVGFESpotLightElement",
            "SVGFESpecularLightingElement",
            "SVGFEPointLightElement",
            "SVGFEOffsetElement",
            "SVGFEMorphologyElement",
            "SVGFEMergeNodeElement",
            "SVGFEMergeElement",
            "SVGFEImageElement",
            "SVGFEGaussianBlurElement",
            "SVGFEFuncRElement",
            "SVGFEFuncGElement",
            "SVGFEFuncBElement",
            "SVGFEFuncAElement",
            "SVGFEFloodElement",
            "SVGFEDropShadowElement",
            "SVGFEDistantLightElement",
            "SVGFEDisplacementMapElement",
            "SVGFEDiffuseLightingElement",
            "SVGFEConvolveMatrixElement",
            "SVGFECompositeElement",
            "SVGFEComponentTransferElement",
            "SVGFEColorMatrixElement",
            "SVGFEBlendElement",
            "SVGEllipseElement",
            "SVGElement",
            "SVGDescElement",
            "SVGDefsElement",
            "SVGComponentTransferFunctionElement",
            "SVGClipPathElement",
            "SVGCircleElement",
            "SVGAnimationElement",
            "SVGAnimatedTransformList",
            "SVGAnimatedString",
            "SVGAnimatedRect",
            "SVGAnimatedPreserveAspectRatio",
            "SVGAnimatedNumberList",
            "SVGAnimatedNumber",
            "SVGAnimatedLengthList",
            "SVGAnimatedLength",
            "SVGAnimatedInteger",
            "SVGAnimatedEnumeration",
            "SVGAnimatedBoolean",
            "SVGAnimatedAngle",
            "SVGAnimateTransformElement",
            "SVGAnimateMotionElement",
            "SVGAnimateElement",
            "SVGAngle",
            "SVGAElement",
            "Response",
            "ResizeObserverSize",
            "ResizeObserverEntry",
            "ResizeObserver",
            "Request",
            "ReportingObserver",
            "ReportBody",
            "ReadableStreamDefaultReader",
            "ReadableStreamDefaultController",
            "ReadableStreamBYOBRequest",
            "ReadableStreamBYOBReader",
            "ReadableStream",
            "ReadableByteStreamController",
            "Range",
            "RadioNodeList",
            "RTCTrackEvent",
            "RTCStatsReport",
            "RTCSessionDescription",
            "RTCSctpTransport",
            "RTCRtpTransceiver",
            "RTCRtpSender",
            "RTCRtpReceiver",
            "RTCPeerConnectionIceEvent",
            "RTCPeerConnectionIceErrorEvent",
            "RTCPeerConnection",
            "RTCIceTransport",
            "RTCIceCandidate",
            "RTCErrorEvent",
            "RTCError",
            "RTCEncodedVideoFrame",
            "RTCEncodedAudioFrame",
            "RTCDtlsTransport",
            "RTCDataChannelEvent",
            "RTCDTMFToneChangeEvent",
            "RTCDTMFSender",
            "RTCCertificate",
            "PromiseRejectionEvent",
            "ProgressEvent",
            "Profiler",
            "ProcessingInstruction",
            "PopStateEvent",
            "PointerEvent",
            "PluginArray",
            "Plugin",
            "PictureInPictureWindow",
            "PictureInPictureEvent",
            "PeriodicWave",
            "PerformanceTiming",
            "PerformanceServerTiming",
            "PerformanceScriptTiming",
            "PerformanceResourceTiming",
            "PerformancePaintTiming",
            "PerformanceObserverEntryList",
            "PerformanceObserver",
            "PerformanceNavigationTiming",
            "PerformanceNavigation",
            "PerformanceMeasure",
            "PerformanceMark",
            "PerformanceLongTaskTiming",
            "PerformanceLongAnimationFrameTiming",
            "PerformanceEventTiming",
            "PerformanceEntry",
            "PerformanceElementTiming",
            "Performance",
            "Path2D",
            "PannerNode",
            "PageTransitionEvent",
            "OverconstrainedError",
            "OscillatorNode",
            "OffscreenCanvasRenderingContext2D",
            "OffscreenCanvas",
            "OfflineAudioContext",
            "OfflineAudioCompletionEvent",
            "Observable",
            "NodeList",
            "NodeIterator",
            "NodeFilter",
            "Node",
            "NetworkInformation",
            "NavigatorUAData",
            "Navigator",
            "NavigationTransition",
            "NavigationHistoryEntry",
            "NavigationDestination",
            "NavigationCurrentEntryChangeEvent",
            "NavigationActivation",
            "Navigation",
            "NavigateEvent",
            "NamedNodeMap",
            "MutationRecord",
            "MutationObserver",
            "MouseEvent",
            "MimeTypeArray",
            "MimeType",
            "MessagePort",
            "MessageEvent",
            "MessageChannel",
            "MediaStreamTrackVideoStats",
            "MediaStreamTrackProcessor",
            "MediaStreamTrackGenerator",
            "MediaStreamTrackEvent",
            "MediaStreamTrackAudioStats",
            "MediaStreamTrack",
            "MediaStreamEvent",
            "MediaStreamAudioSourceNode",
            "MediaStreamAudioDestinationNode",
            "MediaStream",
            "MediaSourceHandle",
            "MediaSource",
            "MediaRecorder",
            "MediaQueryListEvent",
            "MediaQueryList",
            "MediaList",
            "MediaError",
            "MediaEncryptedEvent",
            "MediaElementAudioSourceNode",
            "MediaCapabilities",
            "MathMLElement",
            "Location",
            "LayoutShiftAttribution",
            "LayoutShift",
            "LargestContentfulPaint",
            "KeyframeEffect",
            "KeyboardEvent",
            "IntersectionObserverEntry",
            "IntersectionObserver",
            "InputEvent",
            "InputDeviceInfo",
            "InputDeviceCapabilities",
            "Ink",
            "ImageData",
            "ImageBitmapRenderingContext",
            "ImageBitmap",
            "IdleDeadline",
            "IIRFilterNode",
            "IDBVersionChangeEvent",
            "IDBTransaction",
            "IDBRequest",
            "IDBOpenDBRequest",
            "IDBObjectStore",
            "IDBKeyRange",
            "IDBIndex",
            "IDBFactory",
            "IDBDatabase",
            "IDBCursorWithValue",
            "IDBCursor",
            "History",
            "HighlightRegistry",
            "Highlight",
            "Headers",
            "HashChangeEvent",
            "HTMLVideoElement",
            "HTMLUnknownElement",
            "HTMLUListElement",
            "HTMLTrackElement",
            "HTMLTitleElement",
            "HTMLTimeElement",
            "HTMLTextAreaElement",
            "HTMLTemplateElement",
            "HTMLTableSectionElement",
            "HTMLTableRowElement",
            "HTMLTableElement",
            "HTMLTableColElement",
            "HTMLTableCellElement",
            "HTMLTableCaptionElement",
            "HTMLStyleElement",
            "HTMLSpanElement",
            "HTMLSourceElement",
            "HTMLSlotElement",
            "HTMLSelectElement",
            "HTMLScriptElement",
            "HTMLQuoteElement",
            "HTMLProgressElement",
            "HTMLPreElement",
            "HTMLPictureElement",
            "HTMLParamElement",
            "HTMLParagraphElement",
            "HTMLOutputElement",
            "HTMLOptionsCollection",
            "HTMLOptionElement",
            "HTMLOptGroupElement",
            "HTMLObjectElement",
            "HTMLOListElement",
            "HTMLModElement",
            "HTMLMeterElement",
            "HTMLMetaElement",
            "HTMLMenuElement",
            "HTMLMediaElement",
            "HTMLMarqueeElement",
            "HTMLMapElement",
            "HTMLLinkElement",
            "HTMLLegendElement",
            "HTMLLabelElement",
            "HTMLLIElement",
            "HTMLInputElement",
            "HTMLImageElement",
            "HTMLIFrameElement",
            "HTMLHtmlElement",
            "HTMLHeadingElement",
            "HTMLHeadElement",
            "HTMLHRElement",
            "HTMLFrameSetElement",
            "HTMLFrameElement",
            "HTMLFormElement",
            "HTMLFormControlsCollection",
            "HTMLFontElement",
            "HTMLFieldSetElement",
            "HTMLEmbedElement",
            "HTMLElement",
            "HTMLDocument",
            "HTMLDivElement",
            "HTMLDirectoryElement",
            "HTMLDialogElement",
            "HTMLDetailsElement",
            "HTMLDataListElement",
            "HTMLDataElement",
            "HTMLDListElement",
            "HTMLCollection",
            "HTMLCanvasElement",
            "HTMLButtonElement",
            "HTMLBodyElement",
            "HTMLBaseElement",
            "HTMLBRElement",
            "HTMLAudioElement",
            "HTMLAreaElement",
            "HTMLAnchorElement",
            "HTMLAllCollection",
            "GeolocationPositionError",
            "GeolocationPosition",
            "GeolocationCoordinates",
            "Geolocation",
            "GamepadHapticActuator",
            "GamepadEvent",
            "GamepadButton",
            "Gamepad",
            "GainNode",
            "FormDataEvent",
            "FormData",
            "FontFaceSetLoadEvent",
            "FontFace",
            "FocusEvent",
            "FileReader",
            "FileList",
            "File",
            "FeaturePolicy",
            "External",
            "EventTarget",
            "EventSource",
            "EventCounts",
            "Event",
            "ErrorEvent",
            "EncodedVideoChunk",
            "EncodedAudioChunk",
            "ElementInternals",
            "Element",
            "EditContext",
            "DynamicsCompressorNode",
            "DragEvent",
            "DocumentType",
            "DocumentTimeline",
            "DocumentFragment",
            "Document",
            "DelegatedInkTrailPresenter",
            "DelayNode",
            "DecompressionStream",
            "DataTransferItemList",
            "DataTransferItem",
            "DataTransfer",
            "DOMTokenList",
            "DOMStringMap",
            "DOMStringList",
            "DOMRectReadOnly",
            "DOMRectList",
            "DOMRect",
            "DOMQuad",
            "DOMPointReadOnly",
            "DOMPoint",
            "DOMParser",
            "DOMMatrixReadOnly",
            "DOMMatrix",
            "DOMImplementation",
            "DOMException",
            "DOMError",
            "CustomStateSet",
            "CustomEvent",
            "CustomElementRegistry",
            "Crypto",
            "CountQueuingStrategy",
            "ConvolverNode",
            "ContentVisibilityAutoStateChangeEvent",
            "ConstantSourceNode",
            "CompressionStream",
            "CompositionEvent",
            "Comment",
            "CommandEvent",
            "CloseWatcher",
            "CloseEvent",
            "ClipboardEvent",
            "CharacterData",
            "CharacterBoundsUpdateEvent",
            "ChannelSplitterNode",
            "ChannelMergerNode",
            "CaretPosition",
            "CanvasRenderingContext2D",
            "CanvasPattern",
            "CanvasGradient",
            "CanvasCaptureMediaStreamTrack",
            "CSSViewTransitionRule",
            "CSSVariableReferenceValue",
            "CSSUnparsedValue",
            "CSSUnitValue",
            "CSSTranslate",
            "CSSTransition",
            "CSSTransformValue",
            "CSSTransformComponent",
            "CSSSupportsRule",
            "CSSStyleValue",
            "CSSStyleSheet",
            "CSSStyleRule",
            "CSSStyleDeclaration",
            "CSSStartingStyleRule",
            "CSSSkewY",
            "CSSSkewX",
            "CSSSkew",
            "CSSScopeRule",
            "CSSScale",
            "CSSRuleList",
            "CSSRule",
            "CSSRotate",
            "CSSPropertyRule",
            "CSSPositionValue",
            "CSSPositionTryRule",
            "CSSPositionTryDescriptors",
            "CSSPerspective",
            "CSSPageRule",
            "CSSNumericValue",
            "CSSNumericArray",
            "CSSNestedDeclarations",
            "CSSNamespaceRule",
            "CSSMediaRule",
            "CSSMatrixComponent",
            "CSSMathValue",
            "CSSMathSum",
            "CSSMathProduct",
            "CSSMathNegate",
            "CSSMathMin",
            "CSSMathMax",
            "CSSMathInvert",
            "CSSMathClamp",
            "CSSMarginRule",
            "CSSLayerStatementRule",
            "CSSLayerBlockRule",
            "CSSKeywordValue",
            "CSSKeyframesRule",
            "CSSKeyframeRule",
            "CSSImportRule",
            "CSSImageValue",
            "CSSGroupingRule",
            "CSSFontPaletteValuesRule",
            "CSSFontFaceRule",
            "CSSCounterStyleRule",
            "CSSContainerRule",
            "CSSConditionRule",
            "CSSAnimation",
            "CSS",
            "CSPViolationReportBody",
            "CDATASection",
            "ByteLengthQueuingStrategy",
            "BrowserCaptureMediaStreamTrack",
            "BroadcastChannel",
            "BlobEvent",
            "Blob",
            "BiquadFilterNode",
            "BeforeUnloadEvent",
            "BeforeInstallPromptEvent",
            "BaseAudioContext",
            "BarProp",
            "AudioWorkletNode",
            "AudioSinkInfo",
            "AudioScheduledSourceNode",
            "AudioProcessingEvent",
            "AudioParamMap",
            "AudioParam",
            "AudioNode",
            "AudioListener",
            "AudioDestinationNode",
            "AudioData",
            "AudioContext",
            "AudioBufferSourceNode",
            "AudioBuffer",
            "Attr",
            "AnimationTimeline",
            "AnimationPlaybackEvent",
            "AnimationEvent",
            "AnimationEffect",
            "Animation",
            "AnalyserNode",
            "AbstractRange",
            "AbortSignal",
            "AbortController",
            "window",
            "self",
            "document",
            "name",
            "location",
            "customElements",
            "history",
            "navigation",
            "locationbar",
            "menubar",
            "personalbar",
            "scrollbars",
            "statusbar",
            "toolbar",
            "status",
            "closed",
            "frames",
            "length",
            "top",
            "opener",
            "parent",
            "frameElement",
            "navigator",
            "origin",
            "external",
            "screen",
            "innerWidth",
            "innerHeight",
            "scrollX",
            "pageXOffset",
            "scrollY",
            "pageYOffset",
            "visualViewport",
            "screenX",
            "screenY",
            "outerWidth",
            "outerHeight",
            "devicePixelRatio",
            "event",
            "clientInformation",
            "offscreenBuffering",
            "screenLeft",
            "screenTop",
            "styleMedia",
            "onsearch",
            "trustedTypes",
            "performance",
            "onappinstalled",
            "onbeforeinstallprompt",
            "crypto",
            "indexedDB",
            "sessionStorage",
            "localStorage",
            "onbeforexrselect",
            "onabort",
            "onbeforeinput",
            "onbeforematch",
            "onbeforetoggle",
            "onblur",
            "oncancel",
            "oncanplay",
            "oncanplaythrough",
            "onchange",
            "onclick",
            "onclose",
            "oncommand",
            "oncontentvisibilityautostatechange",
            "oncontextlost",
            "oncontextmenu",
            "oncontextrestored",
            "oncuechange",
            "ondblclick",
            "ondrag",
            "ondragend",
            "ondragenter",
            "ondragleave",
            "ondragover",
            "ondragstart",
            "ondrop",
            "ondurationchange",
            "onemptied",
            "onended",
            "onerror",
            "onfocus",
            "onformdata",
            "oninput",
            "oninvalid",
            "onkeydown",
            "onkeypress",
            "onkeyup",
            "onload",
            "onloadeddata",
            "onloadedmetadata",
            "onloadstart",
            "onmousedown",
            "onmouseenter",
            "onmouseleave",
            "onmousemove",
            "onmouseout",
            "onmouseover",
            "onmouseup",
            "onmousewheel",
            "onpause",
            "onplay",
            "onplaying",
            "onprogress",
            "onratechange",
            "onreset",
            "onresize",
            "onscroll",
            "onscrollend",
            "onsecuritypolicyviolation",
            "onseeked",
            "onseeking",
            "onselect",
            "onslotchange",
            "onstalled",
            "onsubmit",
            "onsuspend",
            "ontimeupdate",
            "ontoggle",
            "onvolumechange",
            "onwaiting",
            "onwebkitanimationend",
            "onwebkitanimationiteration",
            "onwebkitanimationstart",
            "onwebkittransitionend",
            "onwheel",
            "onauxclick",
            "ongotpointercapture",
            "onlostpointercapture",
            "onpointerdown",
            "onpointermove",
            "onpointerrawupdate",
            "onpointerup",
            "onpointercancel",
            "onpointerover",
            "onpointerout",
            "onpointerenter",
            "onpointerleave",
            "onselectstart",
            "onselectionchange",
            "onanimationend",
            "onanimationiteration",
            "onanimationstart",
            "ontransitionrun",
            "ontransitionstart",
            "ontransitionend",
            "ontransitioncancel",
            "onafterprint",
            "onbeforeprint",
            "onbeforeunload",
            "onhashchange",
            "onlanguagechange",
            "onmessage",
            "onmessageerror",
            "onoffline",
            "ononline",
            "onpagehide",
            "onpageshow",
            "onpopstate",
            "onrejectionhandled",
            "onstorage",
            "onunhandledrejection",
            "onunload",
            "isSecureContext",
            "crossOriginIsolated",
            "scheduler",
            "alert",
            "atob",
            "blur",
            "btoa",
            "cancelAnimationFrame",
            "cancelIdleCallback",
            "captureEvents",
            "clearInterval",
            "clearTimeout",
            "close",
            "confirm",
            "createImageBitmap",
            "fetch",
            "find",
            "focus",
            "getComputedStyle",
            "getSelection",
            "matchMedia",
            "moveBy",
            "moveTo",
            "open",
            "postMessage",
            "print",
            "prompt",
            "queueMicrotask",
            "releaseEvents",
            "reportError",
            "requestAnimationFrame",
            "requestIdleCallback",
            "resizeBy",
            "resizeTo",
            "scroll",
            "scrollBy",
            "scrollTo",
            "setInterval",
            "setTimeout",
            "stop",
            "structuredClone",
            "webkitCancelAnimationFrame",
            "webkitRequestAnimationFrame",
            "SuppressedError",
            "DisposableStack",
            "AsyncDisposableStack",
            "Float16Array",
            "chrome",
            "WebAssembly",
            "caches",
            "cookieStore",
            "ondevicemotion",
            "ondeviceorientation",
            "ondeviceorientationabsolute",
            "documentPictureInPicture",
            "sharedStorage",
            "AbsoluteOrientationSensor",
            "Accelerometer",
            "AudioDecoder",
            "AudioEncoder",
            "AudioWorklet",
            "BatteryManager",
            "Cache",
            "CacheStorage",
            "Clipboard",
            "ClipboardItem",
            "CookieChangeEvent",
            "CookieStore",
            "CookieStoreManager",
            "Credential",
            "CredentialsContainer",
            "CryptoKey",
            "DeviceMotionEvent",
            "DeviceMotionEventAcceleration",
            "DeviceMotionEventRotationRate",
            "DeviceOrientationEvent",
            "FederatedCredential",
            "GPU",
            "GPUAdapter",
            "GPUAdapterInfo",
            "GPUBindGroup",
            "GPUBindGroupLayout",
            "GPUBuffer",
            "GPUBufferUsage",
            "GPUCanvasContext",
            "GPUColorWrite",
            "GPUCommandBuffer",
            "GPUCommandEncoder",
            "GPUCompilationInfo",
            "GPUCompilationMessage",
            "GPUComputePassEncoder",
            "GPUComputePipeline",
            "GPUDevice",
            "GPUDeviceLostInfo",
            "GPUError",
            "GPUExternalTexture",
            "GPUInternalError",
            "GPUMapMode",
            "GPUOutOfMemoryError",
            "GPUPipelineError",
            "GPUPipelineLayout",
            "GPUQuerySet",
            "GPUQueue",
            "GPURenderBundle",
            "GPURenderBundleEncoder",
            "GPURenderPassEncoder",
            "GPURenderPipeline",
            "GPUSampler",
            "GPUShaderModule",
            "GPUShaderStage",
            "GPUSupportedFeatures",
            "GPUSupportedLimits",
            "GPUTexture",
            "GPUTextureUsage",
            "GPUTextureView",
            "GPUUncapturedErrorEvent",
            "GPUValidationError",
            "GravitySensor",
            "Gyroscope",
            "IdleDetector",
            "ImageCapture",
            "ImageDecoder",
            "ImageTrack",
            "ImageTrackList",
            "Keyboard",
            "KeyboardLayoutMap",
            "LinearAccelerationSensor",
            "MIDIAccess",
            "MIDIConnectionEvent",
            "MIDIInput",
            "MIDIInputMap",
            "MIDIMessageEvent",
            "MIDIOutput",
            "MIDIOutputMap",
            "MIDIPort",
            "MediaDeviceInfo",
            "MediaDevices",
            "MediaKeyMessageEvent",
            "MediaKeySession",
            "MediaKeyStatusMap",
            "MediaKeySystemAccess",
            "MediaKeys",
            "NavigationPreloadManager",
            "NavigatorManagedData",
            "OrientationSensor",
            "PasswordCredential",
            "ProtectedAudience",
            "RelativeOrientationSensor",
            "ScreenDetailed",
            "ScreenDetails",
            "Sensor",
            "SensorErrorEvent",
            "ServiceWorkerRegistration",
            "StorageManager",
            "SubtleCrypto",
            "VideoDecoder",
            "VideoEncoder",
            "VirtualKeyboard",
            "WGSLLanguageFeatures",
            "WebTransport",
            "WebTransportBidirectionalStream",
            "WebTransportDatagramDuplexStream",
            "WebTransportError",
            "Worklet",
            "XRDOMOverlayState",
            "XRLayer",
            "XRWebGLBinding",
            "AuthenticatorAssertionResponse",
            "AuthenticatorAttestationResponse",
            "AuthenticatorResponse",
            "PublicKeyCredential",
            "Bluetooth",
            "BluetoothCharacteristicProperties",
            "BluetoothDevice",
            "BluetoothRemoteGATTCharacteristic",
            "BluetoothRemoteGATTDescriptor",
            "BluetoothRemoteGATTServer",
            "BluetoothRemoteGATTService",
            "CaptureController",
            "CreateMonitor",
            "DevicePosture",
            "DocumentPictureInPicture",
            "EyeDropper",
            "FetchLaterResult",
            "FileSystemDirectoryHandle",
            "FileSystemFileHandle",
            "FileSystemHandle",
            "FileSystemWritableFileStream",
            "FileSystemObserver",
            "FontData",
            "FragmentDirective",
            "HID",
            "HIDConnectionEvent",
            "HIDDevice",
            "HIDInputReportEvent",
            "IdentityCredential",
            "IdentityCredentialError",
            "IdentityProvider",
            "NavigatorLogin",
            "LanguageDetector",
            "Lock",
            "LockManager",
            "ServiceWorker",
            "ServiceWorkerContainer",
            "NotRestoredReasonDetails",
            "NotRestoredReasons",
            "OTPCredential",
            "PaymentAddress",
            "PaymentRequest",
            "PaymentRequestUpdateEvent",
            "PaymentResponse",
            "PaymentManager",
            "PaymentMethodChangeEvent",
            "Presentation",
            "PresentationAvailability",
            "PresentationConnection",
            "PresentationConnectionAvailableEvent",
            "PresentationConnectionCloseEvent",
            "PresentationConnectionList",
            "PresentationReceiver",
            "PresentationRequest",
            "PressureObserver",
            "PressureRecord",
            "Serial",
            "SerialPort",
            "SharedWorker",
            "StorageBucket",
            "StorageBucketManager",
            "Summarizer",
            "Translator",
            "USB",
            "USBAlternateInterface",
            "USBConfiguration",
            "USBConnectionEvent",
            "USBDevice",
            "USBEndpoint",
            "USBInTransferResult",
            "USBInterface",
            "USBIsochronousInTransferPacket",
            "USBIsochronousInTransferResult",
            "USBIsochronousOutTransferPacket",
            "USBIsochronousOutTransferResult",
            "USBOutTransferResult",
            "WakeLock",
            "WakeLockSentinel",
            "XRAnchor",
            "XRAnchorSet",
            "XRBoundedReferenceSpace",
            "XRCPUDepthInformation",
            "XRCamera",
            "XRDepthInformation",
            "XRFrame",
            "XRHand",
            "XRHitTestResult",
            "XRHitTestSource",
            "XRInputSource",
            "XRInputSourceArray",
            "XRInputSourceEvent",
            "XRInputSourcesChangeEvent",
            "XRJointPose",
            "XRJointSpace",
            "XRLightEstimate",
            "XRLightProbe",
            "XRPose",
            "XRRay",
            "XRReferenceSpace",
            "XRReferenceSpaceEvent",
            "XRRenderState",
            "XRRigidTransform",
            "XRSession",
            "XRSessionEvent",
            "XRSpace",
            "XRSystem",
            "XRTransientInputHitTestResult",
            "XRTransientInputHitTestSource",
            "XRView",
            "XRViewerPose",
            "XRViewport",
            "XRWebGLDepthInformation",
            "XRWebGLLayer",
            "fetchLater",
            "getScreenDetails",
            "queryLocalFonts",
            "showDirectoryPicker",
            "showOpenFilePicker",
            "showSaveFilePicker",
            "originAgentCluster",
            "viewport",
            "onpageswap",
            "onpagereveal",
            "credentialless",
            "fence",
            "launchQueue",
            "speechSynthesis",
            "onscrollsnapchange",
            "onscrollsnapchanging",
            "BackgroundFetchManager",
            "BackgroundFetchRecord",
            "BackgroundFetchRegistration",
            "BluetoothUUID",
            "CSSFontFeatureValuesRule",
            "CSSFunctionDeclarations",
            "CSSFunctionDescriptors",
            "CSSFunctionRule",
            "ChapterInformation",
            "CropTarget",
            "DocumentPictureInPictureEvent",
            "Fence",
            "FencedFrameConfig",
            "HTMLFencedFrameElement",
            "HTMLSelectedContentElement",
            "IntegrityViolationReportBody",
            "LaunchParams",
            "LaunchQueue",
            "MediaMetadata",
            "MediaSession",
            "Notification",
            "PageRevealEvent",
            "PageSwapEvent",
            "PeriodicSyncManager",
            "PermissionStatus",
            "Permissions",
            "PushManager",
            "PushSubscription",
            "PushSubscriptionOptions",
            "QuotaExceededError",
            "RTCDataChannel",
            "RemotePlayback",
            "RestrictionTarget",
            "SharedStorage",
            "SharedStorageWorklet",
            "SharedStorageAppendMethod",
            "SharedStorageClearMethod",
            "SharedStorageDeleteMethod",
            "SharedStorageModifierMethod",
            "SharedStorageSetMethod",
            "SnapEvent",
            "SpeechGrammar",
            "SpeechGrammarList",
            "SpeechRecognition",
            "SpeechRecognitionErrorEvent",
            "SpeechRecognitionEvent",
            "SpeechSynthesis",
            "SpeechSynthesisErrorEvent",
            "SpeechSynthesisEvent",
            "SpeechSynthesisUtterance",
            "SpeechSynthesisVoice",
            "Viewport",
            "WebSocketError",
            "WebSocketStream",
            "webkitSpeechGrammar",
            "webkitSpeechGrammarList",
            "webkitSpeechRecognition",
            "webkitSpeechRecognitionError",
            "webkitSpeechRecognitionEvent",
            "webkitRequestFileSystem",
            "webkitResolveLocalFileSystemURL",
            "RudderSnippetVersion",
            "rudderanalytics",
            "rudderAnalyticsBuildType",
            "rudderAnalyticsAddScript",
            "rudderAnalyticsMount",
            "goVerisoulEnv",
            "goVerisoulProjectId",
            "openBraces",
            "script",
            "warp_app_base_url",
            "warp_app_version",
            "verisoul_env",
            "verisoul_project_id",
            "Verisoul",
            "_hsq",
            "_hsp",
            "RudderStackGlobals",
            "__reactRouterVersion",
            "warpEmitEvent",
            "@wry/context:Slot",
            "warpUserHandoff",
            "__APOLLO_CLIENT__",
            "dataLayer",
            "gtag",
            "__SENTRY__",
            "_0x28b5",
            "_0x70cb",
            "VerisoulBundleInternal",
            "detectIncognito"
        ]

        # 站点特定的 window keys
        SITE_SPECIFIC_WINDOW_KEYS = [
            "RudderSnippetVersion", "rudderanalytics", "rudderAnalyticsBuildType",
            "rudderAnalyticsAddScript", "rudderAnalyticsMount", "goVerisoulEnv",
            "goVerisoulProjectId", "openBraces", "script", "warp_app_base_url",
            "warp_app_version", "verisoul_env", "verisoul_project_id", "Verisoul",
            "_hsq", "_hsp", "RudderStackGlobals", "__reactRouterVersion",
            "warpEmitEvent", "@wry/context:Slot", "warpUserHandoff",
            "__APOLLO_CLIENT__", "dataLayer", "gtag", "__SENTRY__",
            "_0x28b5", "_0x70cb", "VerisoulBundleInternal", "detectIncognito"
        ]

        # 选择配置
        profile = copy.deepcopy(random.choice(BASE_PROFILES_EXTENDED))
        browser_version = random.choice(BROWSER_VERSIONS_COMPLETE)
        lang_config = random.choice(LANGUAGE_CONFIGS_FIXED)

        # 构建 User-Agent
        ua_full_version = browser_version["full_version"]
        if browser_version["browser"] == "Chrome":
            user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ua_full_version} Safari/537.36"
        else:  # Edge
            chromium_version = browser_version.get("full_chromium_version", ua_full_version)
            user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chromium_version} Safari/537.36 Edg/{ua_full_version}"

        app_version = user_agent.replace("Mozilla/", "")

        # 构建品牌信息
        brands = browser_version["brands"]
        full_version_list = []
        for brand_info in brands:
            if "Chrome" in brand_info["brand"] or "Chromium" in brand_info["brand"] or "Edge" in brand_info["brand"]:
                version_str = ua_full_version if "Edge" not in brand_info["brand"] else browser_version.get(
                    "full_version")
                if "Chromium" in brand_info["brand"] and browser_version["browser"] == "Edge":
                    version_str = browser_version.get("full_chromium_version", ua_full_version)
            else:
                version_str = f"{brand_info['version']}.0.0.0"

            full_version_list.append({
                "brand": brand_info["brand"],
                "version": version_str
            })

        # 获取硬件和屏幕配置
        hw_config = profile["hardware_config"]
        screen_config = profile["screen_resolution"]

        # 生成随机打乱的 keyboard_layout
        keyboard_layout_base = [
            {"key": "KeyA", "value": "a"}, {"key": "KeyB", "value": "b"}, {"key": "KeyC", "value": "c"},
            {"key": "KeyD", "value": "d"}, {"key": "KeyE", "value": "e"}, {"key": "KeyF", "value": "f"},
            {"key": "KeyG", "value": "g"}, {"key": "KeyH", "value": "h"}, {"key": "KeyI", "value": "i"},
            {"key": "KeyJ", "value": "j"}, {"key": "KeyK", "value": "k"}, {"key": "KeyL", "value": "l"},
            {"key": "KeyM", "value": "m"}, {"key": "KeyN", "value": "n"}, {"key": "KeyO", "value": "o"},
            {"key": "KeyP", "value": "p"}, {"key": "KeyQ", "value": "q"}, {"key": "KeyR", "value": "r"},
            {"key": "KeyS", "value": "s"}, {"key": "KeyT", "value": "t"}, {"key": "KeyU", "value": "u"},
            {"key": "KeyV", "value": "v"}, {"key": "KeyW", "value": "w"}, {"key": "KeyX", "value": "x"},
            {"key": "KeyY", "value": "y"}, {"key": "KeyZ", "value": "z"}, {"key": "Digit0", "value": "0"},
            {"key": "Digit1", "value": "1"}, {"key": "Digit2", "value": "2"}, {"key": "Digit3", "value": "3"},
            {"key": "Digit4", "value": "4"}, {"key": "Digit5", "value": "5"}, {"key": "Digit6", "value": "6"},
            {"key": "Digit7", "value": "7"}, {"key": "Digit8", "value": "8"}, {"key": "Digit9", "value": "9"},
            {"key": "Backquote", "value": "`"}, {"key": "Minus", "value": "-"}, {"key": "Equal", "value": "="},
            {"key": "Backslash", "value": "\\"}, {"key": "BracketLeft", "value": "["},
            {"key": "BracketRight", "value": "]"}, {"key": "Semicolon", "value": ";"},
            {"key": "Quote", "value": "'"}, {"key": "Comma", "value": ","}, {"key": "Period", "value": "."},
            {"key": "Slash", "value": "/"}, {"key": "IntlBackslash", "value": "\\"}
        ]
        random.shuffle(keyboard_layout_base)  # 关键：随机打乱顺序

        # 生成正确的 performance_timing
        now = int(datetime.now().timestamp() * 1000)
        navigation_start = now - random.randint(3000, 6000)
        fetch_start = navigation_start + random.randint(2, 10)
        domain_lookup_start = fetch_start + random.randint(1, 20)
        domain_lookup_end = domain_lookup_start + random.randint(10, 50)
        connect_start = domain_lookup_end
        secure_connection_start = connect_start + random.randint(5, 15) if random.random() > 0.3 else 0
        connect_end = (secure_connection_start if secure_connection_start else connect_start) + random.randint(20, 60)
        request_start = connect_end + random.randint(1, 5)
        response_start = request_start + random.randint(80, 200)
        response_end = response_start + random.randint(1, 10)
        dom_loading = response_end + random.randint(1, 10)
        unload_event_start = dom_loading + random.randint(1, 5)
        unload_event_end = unload_event_start + random.randint(1, 3)
        dom_interactive = dom_loading + random.randint(200, 500)
        dom_content_loaded_event_start = dom_interactive + random.randint(100, 300)
        dom_content_loaded_event_end = dom_content_loaded_event_start + random.randint(1, 5)

        # 50% 概率页面已完全加载
        if random.random() > 0.5:
            dom_complete = dom_content_loaded_event_end + random.randint(50, 200)
            load_event_start = dom_complete + random.randint(1, 5)
            load_event_end = load_event_start + random.randint(1, 5)
        else:
            dom_complete = 0
            load_event_start = 0
            load_event_end = 0

        performance_timing = {
            "navigation_start": navigation_start,
            "redirect_start": 0,
            "redirect_end": 0,
            "fetch_start": fetch_start,
            "domain_lookup_start": domain_lookup_start,
            "domain_lookup_end": domain_lookup_end,
            "connect_start": connect_start,
            "secure_connection_start": secure_connection_start,
            "connect_end": connect_end,
            "request_start": request_start,
            "response_start": response_start,
            "response_end": response_end,
            "unload_event_start": unload_event_start,
            "unload_event_end": unload_event_end,
            "dom_loading": dom_loading,
            "dom_interactive": dom_interactive,
            "dom_content_loaded_event_start": dom_content_loaded_event_start,
            "dom_content_loaded_event_end": dom_content_loaded_event_end,
            "dom_complete": dom_complete,
            "load_event_start": load_event_start,
            "load_event_end": load_event_end
        }

        # 权限配置
        permissions = {
            "accessibility_events": "Failed to execute 'query' on 'Permissions': Failed to read the 'name' property from 'PermissionDescriptor': The provided value 'accessibility-events' is not a valid enum value of type PermissionName.",
            "ambient_light_sensor": "Failed to execute 'query' on 'Permissions': GenericSensorExtraClasses flag is not enabled.",
            "bluetooth": "Failed to execute 'query' on 'Permissions': Failed to read the 'name' property from 'PermissionDescriptor': The provided value 'bluetooth' is not a valid enum value of type PermissionName.",
            "nfc": "Failed to execute 'query' on 'Permissions': Web NFC is not enabled.",
            "push": "Failed to execute 'query' on 'Permissions': Push Permission without userVisibleOnly:true isn't supported yet.",
            "speaker": "Failed to execute 'query' on 'Permissions': Failed to read the 'name' property from 'PermissionDescriptor': The provided value 'speaker' is not a valid enum value of type PermissionName.",
            "speaker_selection": "Failed to execute 'query' on 'Permissions': The Speaker Selection API is not enabled.",
            "top_level_storage_access": "Failed to execute 'query' on 'Permissions': The requested origin is invalid.",
            "accelerometer": "granted",
            "background_sync": "granted",
            "background_fetch": "granted",
            "camera": random.choice(["denied", "prompt"]),
            "clipboard_read": random.choice(["prompt", "granted"]),
            "clipboard_write": "granted",
            "geolocation": random.choice(["denied", "prompt"]),
            "gyroscope": "granted",
            "local_fonts": "prompt",
            "magnetometer": "granted",
            "microphone": random.choice(["denied", "prompt"]),
            "midi": "prompt",
            "notifications": random.choice(["denied", "prompt", "granted"]),
            "payment_handler": "granted",
            "persistent_storage": "prompt",
            "screen_wake_lock": "granted",
            "storage_access": "granted",
            "window_management": "prompt"
        }

        # 构建 window_keys
        window_keys = base_window_keys.copy()
        for site_key in SITE_SPECIFIC_WINDOW_KEYS:
            if site_key not in window_keys:
                window_keys.append(site_key)

        # 隐身模式对存储的影响
        incognito = random.choice([0, 1])
        if incognito == 1:
            storage_quota = random.randint(1000000000, 2000000000)
            storage_usage = 0
        else:
            storage_quota = random.randint(100000000000, 200000000000)
            storage_usage = random.randint(1000, 10000000)

        # 网络连接信息
        connection_rtt = random.choice([50, 100, 150, 200, 250, 300])
        connection_downlink = random.choice([0.35, 0.7, 1.25, 1.3, 1.5, 2.5, 5.0, 10.0])
        connection_effective_type = random.choice(["slow-2g", "2g", "3g", "4g"])

        # 电池信息
        battery_charging = random.choice([0, 1])
        battery_level = round(random.uniform(0.3, 1.0), 2)

        # 完整的 payload 构建
        payload = {
            # 基础标识信息
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "browser_id": str(uuid.uuid4()),
            "project_id": "27fcb93a-7693-486d-b969-a9d96f799f91",
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "is_v2": True,
            "event": "device_minmet",

            # Window 和 Document
            "window_keys": window_keys,
            "document_element_keys": ["lang"],

            # 引擎信息
            "engine": "WebKit",

            # 触摸支持
            "max_touch_points": 0 if profile["os"] == "Windows" else 1,

            # 语言设置
            "language": lang_config["lang"],
            "languages": lang_config["languages"],

            # Cookie (需要从实际请求中获取)
            "document_cookies": "",

            # 性能时间
            "performance_timing": performance_timing,

            # Navigator 属性
            "app_code_name": "Mozilla",
            "app_name": "Netscape",
            "app_version": app_version,
            "device_memory": hw_config["memory"],
            "hardware_concurrency": hw_config["cores"],
            "platform": profile["platform"],
            "product": "Gecko",
            "product_sub": "20030107",
            "user_agent": user_agent,
            "vendor": profile["vendor"],
            "vendor_sub": "empty_string",
            "cookie_enabled": 1,
            "do_not_track": -888,
            "webdriver": 0,
            "on_line": 1,

            # JavaScript 堆内存信息
            "js_heap_size_limit": random.randint(2147483648, 4294967296),
            "used_js_heap_size": random.randint(5000000, 50000000),
            "total_js_heap_size": random.randint(7000000, 60000000),

            # 历史记录长度
            "history_length": random.randint(1, 15),

            # 屏幕信息
            "screen_avail_height": screen_config["height"] - random.randint(40, 80),
            "screen_avail_width": screen_config["width"],
            "screen_avail_left": 0,
            "screen_avail_top": 0,
            "screen_color_depth": 24,
            "screen_height": screen_config["height"],
            "screen_pixel_depth": 24,
            "screen_width": screen_config["width"],
            "screen_is_extended": random.choice([0, 1]),
            "screen_orientation_angle": 0,
            "screen_orientation_type": "landscape-primary",

            # 窗口信息
            "window_inner_width": min(screen_config["width"], random.randint(700, screen_config["width"])),
            "window_inner_height": screen_config["height"] - random.randint(100, 200),
            "window_outer_width": screen_config["width"],
            "window_outer_height": screen_config["height"] - random.randint(40, 80),
            "window_external_to_string": "[object External]",

            # 函数字符串表示
            "eval_to_string": "function eval() { [native code] }",

            # Apple Pay 支持
            "apple_pay": 0,

            # 网络连接信息
            "connection_rtt": connection_rtt,
            "connection_downlink": connection_downlink,
            "connection_save_data": 0,
            "connection_effective_type": connection_effective_type,

            # GPU 信息
            "navigator_gpu_preferred_canvas_format": "bgra8unorm",

            # 虚拟键盘边界
            "virtual_keyboard_bounding_box": {
                "x": 0, "y": 0, "width": 0, "height": 0,
                "top": 0, "right": 0, "bottom": 0, "left": 0
            },

            # 标题栏区域边界
            "title_bar_area_bounding_box": {
                "x": 0, "y": 0, "width": 0, "height": 0,
                "top": 0, "right": 0, "bottom": 0, "left": 0
            },

            # 广告相关
            "navigator_can_load_ad_auction_fenced_frame": 0,

            # 视频帧颜色空间
            "video_frame_color_space": {
                "full_range": True,
                "matrix": "rgb",
                "primaries": "bt709",
                "transfer": "iec61966-2-1"
            },

            # 触摸支持
            "supports_touch": 0,

            # 时区偏移
            "timezone_offset": lang_config["timezone_offset"],

            # 国际化日期格式
            "intl_date": {
                "locale": lang_config["lang"],
                "calendar": "gregory",
                "numbering_system": "latn",
                "time_zone": lang_config["timezone"],
                "year": "numeric",
                "month": "numeric",
                "day": "numeric"
            },

            # 国际化数字格式
            "intl_number": {
                "locale": lang_config["lang"],
                "numbering_system": "latn",
                "style": "decimal",
                "minimum_integer_digits": 1,
                "minimum_fraction_digits": 0,
                "maximum_fraction_digits": 3,
                "use_grouping": "auto",
                "notation": "standard",
                "sign_display": "auto",
                "rounding_increment": 1,
                "rounding_mode": "halfExpand",
                "rounding_priority": "auto",
                "trailing_zero_display": "auto"
            },

            # 各种哈希值 (使用配置中的预定义值)
            "prototype_hash": profile["hashes"]["prototype_hash"],
            "math_hash": profile["hashes"]["math_hash"],
            "architecture_test": 255,
            "gpu_vendor": profile["gpu_vendor_string"],
            "gpu_renderer": profile["gpu_renderer"],
            "offline_audio_hash": profile["hashes"]["offline_audio_hash"],
            "mime_types_hash": profile["hashes"]["mime_types_hash"],
            "errors_hash": profile["hashes"]["errors_hash"],

            # 隐私模式
            "incognito": incognito,

            # 存储配额
            "storage_quota": storage_quota,
            "storage_usage": storage_usage,

            # 蓝牙
            "bluetooth": 1,

            # 电池信息
            "battery_charging": battery_charging,
            "battery_charging_time": 0 if battery_charging else random.randint(1000, 10000),
            "battery_discharging_time": 999999999999 if battery_charging else random.randint(10000, 100000),
            "battery_level": battery_level,

            # XR 支持
            "xr_inline": 1,

            # 管理配置
            "is_managed_configuration": 0,

            # 键盘布局
            "keyboard_layout": keyboard_layout_base,

            # 品牌信息
            "brands": brands,
            "mobile": 0,
            "architecture": profile["architecture"],
            "bitness": profile["bitness"],
            "form_factor": "null_string",
            "full_version_list": full_version_list,
            "model": "empty_string",
            "platform_version": profile["os_version"] if browser_version["browser"] == "Chrome" else "19.0.0",
            "ua_full_version": ua_full_version,
            "wow_64": 0,

            # 权限
            "permissions": permissions
        }

        return payload

    async def _send_worker_request(self, session_id: str) -> bool:
        """
        发送worker请求到Verisoul
        """
        try:
            # 生成worker数据
            worker_data = await self._generate_worker_payload(session_id)

            # 从async_client提取cookies并格式化
            cookie_parts = []
            for name, value in self.async_client.cookies.items():
                cookie_parts.append(f"{name}={value}")

            worker_data['document_cookies'] = "; ".join(cookie_parts) if cookie_parts else ""

            # 发送POST请求
            response = await self.async_client.post(
                url="https://ingest.prod.verisoul.ai/worker",
                json=worker_data,
                headers={
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/json",
                    "Origin": "https://app.warp.dev"
                }
            )

            logger.info(f"Verisoul /worker 请求响应: {response.status_code}")

            if response.status_code in [200, 201, 202, 204]:
                logger.info("✅ Worker数据上报成功")
                return True
            else:
                logger.error(f"Worker数据上报失败: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Worker请求失败: {e}")
            return False

    async def _get_public_ip(self) -> str:
        """使用当前会话的代理，访问 IP查询服务 来获取出口公网 IP。"""
        try:
            # 使用一个可靠的 IP 查询服务
            response = await self.async_client.get("https://api.ipify.org?format=json", timeout=10)
            response.raise_for_status()
            ip = response.json()["ip"]
            logger.info(f"成功获取到出口公网 IP: {ip}")
            return ip
        except Exception as e:
            logger.error(f"获取公网 IP 失败: {e}. 将使用一个随机IP作为备用。")
            # 如果失败，生成一个随机的公网IP作为备用，虽然这降低了真实性，但比失败要好
            return f"{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"

    async def _generate_webrtc_sdp(self) -> str:
        """
        动态生成一个高度仿真的 WebRTC SDP 字符串。
        这个函数模仿了浏览器在创建 WebRTC 连接时生成的指纹。
        """
        # 1. 获取我们当前的公网 IP，这是 srflx (server reflexive) 候选项的关键
        public_ip = await self._get_public_ip()

        # 2. 生成会话和连接所需的随机组件
        session_id_num = str(int(time.time() * 1000)) + str(random.randint(1000, 9999))
        local_mdns_host = f"{uuid.uuid4()}.local"
        ice_ufrag = secrets.token_urlsafe(4)
        ice_pwd = secrets.token_urlsafe(24)

        # 3. 生成一个随机的 DTLS 证书指纹 (SHA-256)
        fingerprint_bytes = secrets.token_bytes(32)
        fingerprint_str = ":".join(f"{b:02X}" for b in fingerprint_bytes)

        # 4. SDP 模板。大部分的音视频编解码器信息(rtpmap, fmtp)对于同一浏览器版本是固定的。
        # 我们将动态部分用占位符表示，然后填充它们。
        # 这个模板是基于你提供的 Chrome 风格的 SDP 精心构造的。
        sdp_lines = [
            "v=0",
            f"o=- {session_id_num} 2 IN IP4 127.0.0.1",
            "s=-",
            "t=0 0",
            "a=group:BUNDLE 0 1 2",
            "a=extmap-allow-mixed",
            "a=msid-semantic: WMS",

            # --- Audio Section ---
            f"m=audio {random.randint(10000, 60000)} UDP/TLS/RTP/SAVPF 111 103 104 9 0 8 106 105 13 110 112 113 126",
            f"c=IN IP4 {public_ip}",
            "a=rtcp:9 IN IP4 0.0.0.0",
            # Host candidate (本机地址)
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 2113937151 {local_mdns_host} {random.randint(10000, 60000)} typ host generation 0 network-cost 999",
            # Srflx candidate (公网地址)
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 1677729535 {public_ip} {random.randint(10000, 60000)} typ srflx raddr 0.0.0.0 rport 0 generation 0 network-cost 999",
            f"a=ice-ufrag:{ice_ufrag}",
            f"a=ice-pwd:{ice_pwd}",
            f"a=fingerprint:sha-256 {fingerprint_str}",
            "a=setup:actpass", "a=mid:0", "a=extmap:1 urn:ietf:params:rtp-hdrext:ssrc-audio-level", "a=recvonly",
            "a=rtcp-mux",
            *self._get_audio_codecs(),

            # --- Video Section ---
            f"m=video {random.randint(10000, 60000)} UDP/TLS/RTP/SAVPF 96 97 98 99 100 101 102 123 127 121 125 107 108 109 35 36 124",
            f"c=IN IP4 {public_ip}",
            "a=rtcp:9 IN IP4 0.0.0.0",
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 2113937151 {local_mdns_host} {random.randint(10000, 60000)} typ host generation 0 network-cost 999",
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 1677729535 {public_ip} {random.randint(10000, 60000)} typ srflx raddr 0.0.0.0 rport 0 generation 0 network-cost 999",
            f"a=ice-ufrag:{ice_ufrag}",
            f"a=ice-pwd:{ice_pwd}",
            f"a=fingerprint:sha-256 {fingerprint_str}",
            "a=setup:actpass", "a=mid:1", "a=extmap:14 urn:ietf:params:rtp-hdrext:toffset", "a=recvonly", "a=rtcp-mux",
            *self._get_video_codecs(),

            # --- Application/Data Channel Section ---
            f"m=application {random.randint(10000, 60000)} UDP/DTLS/SCTP webrtc-datachannel",
            f"c=IN IP4 {public_ip}",
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 2113937151 {local_mdns_host} {random.randint(10000, 60000)} typ host generation 0 network-cost 999",
            f"a=candidate:{random.randint(1E9, 4E9)} 1 udp 1677729535 {public_ip} {random.randint(10000, 60000)} typ srflx raddr 0.0.0.0 rport 0 generation 0 network-cost 999",
            f"a=ice-ufrag:{ice_ufrag}",
            f"a=ice-pwd:{ice_pwd}",
            f"a=fingerprint:sha-256 {fingerprint_str}",
            "a=setup:actpass", "a=mid:2", "a=sctp-port:5000", "a=max-message-size:262144"
        ]

        # 5. 使用 '\r\n' 连接所有行，这是 SDP 协议的标准
        return "\r\n".join(sdp_lines) + "\r\n"

    def _get_audio_codecs(self):
        # 这部分是从真实浏览器抓包中提取的，对于一个浏览器版本来说是相对固定的
        return [
            "a=rtpmap:111 opus/48000/2", "a=rtcp-fb:111 transport-cc", "a=fmtp:111 minptime=10;useinbandfec=1",
            "a=rtpmap:103 G722/8000", "a=rtpmap:104 G722/8000", "a=rtpmap:9 G722/8000", "a=rtpmap:0 PCMU/8000",
            "a=rtpmap:8 PCMA/8000", "a=rtpmap:106 CN/32000", "a=rtpmap:105 CN/16000", "a=rtpmap:13 CN/8000",
            "a=rtpmap:110 telephone-event/48000", "a=rtpmap:112 telephone-event/32000",
            "a=rtpmap:113 telephone-event/16000", "a=rtpmap:126 telephone-event/8000"
        ]

    def _get_video_codecs(self):
        # 同样，这部分也是浏览器指纹的一部分
        return [
            "a=rtpmap:96 VP8/90000", "a=rtcp-fb:96 goog-remb", "a=rtcp-fb:96 transport-cc", "a=rtcp-fb:96 ccm fir",
            "a=rtcp-fb:96 nack", "a=rtcp-fb:96 nack pli",
            "a=rtpmap:97 rtx/90000", "a=fmtp:97 apt=96",
            "a=rtpmap:98 VP9/90000", "a=rtcp-fb:98 goog-remb", "a=rtcp-fb:98 transport-cc", "a=rtcp-fb:98 ccm fir",
            "a=rtcp-fb:98 nack", "a=rtcp-fb:98 nack pli", "a=fmtp:98 profile-id=0",
            "a=rtpmap:99 rtx/90000", "a=fmtp:99 apt=98",
            "a=rtpmap:100 H264/90000", "a=rtcp-fb:100 goog-remb", "a=rtcp-fb:100 transport-cc", "a=rtcp-fb:100 ccm fir",
            "a=rtcp-fb:100 nack", "a=rtcp-fb:100 nack pli",
            "a=fmtp:100 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f",
            "a=rtpmap:101 rtx/90000", "a=fmtp:101 apt=100",
            "a=rtpmap:123 red/90000", "a=rtpmap:127 ulpfec/90000"
        ]

    async def register_account(self, email_info: Dict) -> Optional[str]:
        """执行完整的注册流程"""
        email = email_info['email']
        email_password = email_info.get('email_password')
        client_id = email_info.get('client_id')
        outlook_refresh_token = email_info.get('refresh_token')

        # 尝试多个代理
        for proxy_attempt in range(config.MAX_PROXY_RETRIES):
            # 获取新代理
            proxy_str = await self.proxy_manager.get_proxy()
            if not proxy_str:
                logger.error(f"[{email}] 无法获取代理")
                continue

            proxy = self.proxy_manager.format_proxy_for_httpx(proxy_str)
            logger.info(f"[{email}] 第{proxy_attempt + 1}次尝试，使用代理: {proxy_str}")

            # 初始化httpx异步客户端
            self.async_client = httpx.AsyncClient(
                proxy=proxy,
                # proxy="http://127.0.0.1:7897",  # 本地代理
                verify=False,
                timeout=httpx.Timeout(60.0),
                cookies=httpx.Cookies()  # 启用cookie管理
            )

            try:
                # =========================================================
                #  全新的 Verisoul 验证流程
                # =========================================================

                # 步骤 1: 生成一个本地 session_id
                session_id = str(uuid.uuid4())
                logger.info(f"[{email}] Verisoul 流程开始, Session ID: {session_id}")

                # 步骤 2: 发送worker数据
                logger.info(f"[{email}] 发送worker数据...")
                worker_success = await self._send_worker_request(session_id)
                if not worker_success:
                    logger.warning("Worker数据上报失败，但继续尝试...")

                # =========================================================
                #  Verisoul 验证流程结束，现在 session_id 是合法的了
                # =========================================================

                # Step 1: 获取access_token
                logger.info(f"获取access_token...")
                access_token = await self.get_new_access_token(outlook_refresh_token, client_id)
                if not access_token:
                    logger.error("获取access_token失败")
                    continue

                # Step 2: 发送登录请求
                logger.info(f"发送登录请求: {email}")
                signin_result = await self.send_email_signin_request(email, proxy)

                # 如果是代理错误，换代理重试
                if not signin_result["success"]:
                    if signin_result.get("error") == "proxy_error":
                        logger.warning(f"代理错误，更换代理重试...")
                        continue
                    else:
                        logger.error(f"发送登录请求失败: {signin_result.get('error')}")
                        continue

                # Step 3: 等待验证邮件
                logger.info("等待验证邮件...")
                await asyncio.sleep(5)

                email_result = await self.wait_for_verification_email(
                    access_token=access_token,
                    email=email,
                    client_id=client_id,
                    refresh_token=outlook_refresh_token,
                )

                if not email_result:
                    logger.error("未收到验证邮件")
                    continue

                oob_code = email_result.get('oob_code')
                if not oob_code:
                    logger.error("未能提取验证码")
                    continue

                verification_link = email_result.get('verification_link')
                if not verification_link:
                    logger.error("未能提取验证链接")
                    continue

                # Step 4: 完成登录
                logger.info("完成登录...")
                complete_result = await self.complete_email_signin(email, oob_code)

                if not complete_result["success"]:
                    if complete_result.get("error") == "proxy_error":
                        logger.warning(f"代理错误，更换代理重试...")
                        continue
                    else:
                        logger.error(f"完成登录失败: {complete_result.get('error')}")
                        continue

                # Step 5: 激活Warp用户
                logger.info("激活Warp用户...")
                activation_result = await self.activate_warp_user(complete_result["id_token"], session_id)

                if not activation_result["success"]:
                    logger.error(f"[{email}] 账号因违反服务条款被标记，跳过此账号")
                    return None  # 直接返回，不再重试

                request_limit_result = await self._get_request_limit(complete_result["id_token"])

                # Step 6: 保存到数据库
                await self.db_manager.add_account(
                    email=email,
                    email_password=email_password,
                    local_id=complete_result["local_id"],
                    id_token=complete_result["id_token"],
                    refresh_token=complete_result["refresh_token"],
                    client_id=client_id,
                    outlook_refresh_token=outlook_refresh_token,
                    status='active',
                    proxy_info=proxy_str,
                    user_agent=self.user_agent
                )

                logger.info(f"✅ 注册成功: {email}")
                return complete_result["local_id"]

            except Exception as e:
                logger.error(f"注册过程出错: {e}")
                if proxy_attempt < config.MAX_PROXY_RETRIES - 1:
                    logger.info(f"将更换代理重试...")
                    await asyncio.sleep(2)
                    continue

        logger.error(f"[{email}] 尝试了{config.MAX_PROXY_RETRIES}个代理后仍然失败")
        return None

    async def _get_user_info(self, id_token: str) -> Dict[str, Any]:
        """获取账户请求额度

        调用 GetUser 接口获取账户信息，通过 billingMetadata 判断额度
        billingMetadata 为 null → 150 额度
        billingMetadata 不为 null → 2500 额度

        Args:
            id_token: Firebase ID Token

        Returns:
            包含额度信息的字典
        """
        if not id_token:
            return {"success": False, "error": "缺少Firebase ID Token"}

        try:
            url = "https://app.warp.dev/graphql/v2"

            # 查询结构：获取 billingMetadata 来判断额度
            # billingMetadata 是对象类型，需要查询子字段
            query = """
            query GetUser($requestContext: RequestContext!) {
              user(requestContext: $requestContext) {
                __typename
                ... on UserOutput {
                  user {
                    billingMetadata {
                      __typename
                    }
                    profile {
                      email
                      uid
                    }
                    isOnboarded
                  }
                }
                ... on UserFacingError {
                  error {
                    message
                  }
                }
              }
            }
            """

            # 获取 OS 信息
            import platform
            import uuid
            os_name = "Windows"
            os_version = "10 (19045)"
            os_category = "Windows"

            data = {
                "operationName": "GetUser",
                "variables": {
                    "requestContext": {
                        "clientContext": {
                            "version": "v0.2025.09.10.08.11.stable_01"
                        },
                        "osContext": {
                            "category": os_category,
                            "linuxKernelVersion": None,
                            "name": os_name,
                            "version": os_version
                        }
                    }
                },
                "query": query
            }

            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {id_token}",
                "x-warp-client-version": "v0.2025.09.10.08.11.stable_01",
                "x-warp-os-category": "Windows",
                "x-warp-os-name": "Windows",
                "x-warp-os-version": "10 (19045)",
                "X-warp-experiment-id": str(uuid.uuid4())
            }

            print("📊 调用GetUse接口...")

            response = await self.async_client.post(
                url,
                params={"op": "GetUser"},
                json=data,
                headers=headers,
            )

            if response.status_code == 200:
                result = response.json()

                # 检查是否有错误
                if "errors" in result:
                    error_msg = result["errors"][0].get("message", "Unknown error")
                    print(f"❌ GraphQL错误: {error_msg}")
                    return {"success": False, "error": error_msg}

                # 解析响应：data.user.user
                data_result = result.get("data", {})
                user_data = data_result.get("user", {})

                if user_data.get("__typename") == "UserOutput":
                    user_info = user_data.get("user", {})
                    billing_metadata = user_info.get("billingMetadata")
                    profile = user_info.get("profile", {})

                    # 根据 billingMetadata 判断额度
                    # billingMetadata 为 null → 150 额度
                    # billingMetadata 不为 null → 2500 额度
                    if billing_metadata is None:
                        request_limit = 150
                        quota_type = "📋 普通额度"
                    else:
                        request_limit = 2500
                        quota_type = "🎉 高额度"

                    email = profile.get("email", "N/A")
                    uid = profile.get("uid", "N/A")

                    print(f"✅ 账户额度信息:")
                    print(f"   📧 邮箱: {email}")
                    print(f"   🎯 UID: {uid}")
                    print(f"   {quota_type}: {request_limit}")
                    print(f"   📊 billingMetadata: {'null' if billing_metadata is None else 'exists'}")

                    return {
                        "success": True,
                        "requestLimit": request_limit,
                        "quotaType": "high" if request_limit == 2500 else "normal",
                        "email": email,
                        "uid": uid,
                        "hasBillingMetadata": billing_metadata is not None
                    }
                elif user_data.get("__typename") == "UserFacingError":
                    error = user_data.get("error", {}).get("message", "Unknown error")
                    print(f"❌ 获取额度失败: {error}")
                    return {"success": False, "error": error}
                else:
                    print(f"❌ 响应中没有找到用户信息")
                    return {"success": False, "error": "未找到用户信息"}
            else:
                error_text = response.text[:500]
                print(f"❌ HTTP错误 {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {error_text}"}

        except Exception as e:
            print(f"❌ 获取额度错误: {e}")
            return {"success": False, "error": str(e)}

    async def _get_request_limit(self, id_token: str) -> Dict[str, Any]:
        """获取账户请求额度

        调用 GetUser 接口获取账户信息，通过 billingMetadata 判断额度
        billingMetadata 为 null → 150 额度
        billingMetadata 不为 null → 2500 额度

        Args:
            id_token: Firebase ID Token

        Returns:
            包含额度信息的字典
        """

        if not id_token:
            return {"success": False, "error": "缺少Firebase ID Token"}

        try:
            url = "https://app.warp.dev/graphql/v2"

            # 查询结构：获取 billingMetadata 来判断额度
            # billingMetadata 是对象类型，需要查询子字段
            query = """query GetRequestLimitInfo($requestContext: RequestContext!) {\n  user(requestContext: $requestContext) {\n    __typename\n    ... on UserOutput {\n      user {\n        requestLimitInfo {\n          isUnlimited\n          nextRefreshTime\n          requestLimit\n          requestsUsedSinceLastRefresh\n          requestLimitRefreshDuration\n          isUnlimitedAutosuggestions\n          acceptedAutosuggestionsLimit\n          acceptedAutosuggestionsSinceLastRefresh\n          isUnlimitedVoice\n          voiceRequestLimit\n          voiceRequestsUsedSinceLastRefresh\n          voiceTokenLimit\n          voiceTokensUsedSinceLastRefresh\n          isUnlimitedCodebaseIndices\n          maxCodebaseIndices\n          maxFilesPerRepo\n          embeddingGenerationBatchSize\n        }\n      }\n    }\n    ... on UserFacingError {\n      error {\n        __typename\n        ... on SharedObjectsLimitExceeded {\n          limit\n          objectType\n          message\n        }\n        ... on PersonalObjectsLimitExceeded {\n          limit\n          objectType\n          message\n        }\n        ... on AccountDelinquencyError {\n          message\n        }\n        ... on GenericStringObjectUniqueKeyConflict {\n          message\n        }\n      }\n      responseContext {\n        serverVersion\n      }\n    }\n  }\n}\n"""

            # 获取 OS 信息
            import platform
            import uuid
            os_category = "Web"
            os_name = "Windows"
            os_version = "NT 10.0"
            app_version = "v0.2025.10.01.08.12.stable_02"

            data = {
                "operationName": "GetRequestLimitInfo",
                "variables": {
                    "requestContext": {
                        "clientContext": {
                            "version": app_version
                        },
                        "osContext": {
                            "category": os_category,
                            "linuxKernelVersion": None,
                            "name": os_name,
                            "version": os_version
                        }
                    }
                },
                "query": query
            }

            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {id_token}",
                "x-warp-client-id": "warp-app",
                "x-warp-client-version": app_version,
                "x-warp-os-category": os_category,
                "x-warp-os-name": os_name,
                "x-warp-os-version": os_version,
            }

            print("📊 调用GetRequestLimitInfo接口...")

            response = await self.async_client.post(
                url,
                params={"op": "GetRequestLimitInfo"},
                json=data,
                headers=headers,
            )

            if response.status_code == 200:
                result = response.json()

                # 检查是否有错误
                if "errors" in result:
                    error_msg = result["errors"][0].get("message", "Unknown error")
                    print(f"❌ GraphQL错误: {error_msg}")
                    return {"success": False, "error": error_msg}

                # 解析响应：data.user.user.requestLimitInfo
                data_result = result.get("data", {})
                user_data = data_result.get("user", {})

                if user_data.get("__typename") == "UserOutput":
                    user_info = user_data.get("user", {})
                    request_limit_info = user_info.get("requestLimitInfo", {})

                    # 从 requestLimitInfo 获取额度信息
                    request_limit = request_limit_info.get("requestLimit", 0)
                    requests_used = request_limit_info.get("requestsUsedSinceLastRefresh", 0)
                    is_unlimited = request_limit_info.get("isUnlimited", False)
                    next_refresh_time = request_limit_info.get("nextRefreshTime", "N/A")
                    refresh_duration = request_limit_info.get("requestLimitRefreshDuration", "WEEKLY")

                    # 剩余额度
                    requests_remaining = request_limit - requests_used

                    # 判断额度类型
                    if is_unlimited:
                        quota_type = "🚀 无限额度"
                    elif request_limit >= 2500:
                        quota_type = "🎉 高额度"
                    else:
                        quota_type = "📋 普通额度"

                    print(f"✅ 账户额度信息:")
                    print(f"   {quota_type}: {request_limit}")
                    print(f"   📊 已使用: {requests_used}/{request_limit}")
                    print(f"   💎 剩余: {requests_remaining}")
                    print(f"   🔄 刷新周期: {refresh_duration}")
                    print(f"   ⏰ 下次刷新: {next_refresh_time}")

                    # 额外的限制信息
                    if request_limit_info.get("isUnlimitedAutosuggestions"):
                        print(f"   ✨ 自动建议: 无限制")
                    if request_limit_info.get("maxCodebaseIndices"):
                        print(f"   📚 最大代码库索引: {request_limit_info.get('maxCodebaseIndices')}")

                    return {
                        "success": True,
                        "requestLimit": request_limit,
                        "requestsUsed": requests_used,
                        "requestsRemaining": requests_remaining,
                        "isUnlimited": is_unlimited,
                        "nextRefreshTime": next_refresh_time,
                        "refreshDuration": refresh_duration,
                        "quotaType": "unlimited" if is_unlimited else ("high" if request_limit >= 2500 else "normal"),
                        # 其他信息
                        "autosuggestions": {
                            "isUnlimited": request_limit_info.get("isUnlimitedAutosuggestions", False),
                            "limit": request_limit_info.get("acceptedAutosuggestionsLimit", 0),
                            "used": request_limit_info.get("acceptedAutosuggestionsSinceLastRefresh", 0)
                        },
                        "voice": {
                            "isUnlimited": request_limit_info.get("isUnlimitedVoice", False),
                            "requestLimit": request_limit_info.get("voiceRequestLimit", 0),
                            "requestsUsed": request_limit_info.get("voiceRequestsUsedSinceLastRefresh", 0),
                            "tokenLimit": request_limit_info.get("voiceTokenLimit", 0),
                            "tokensUsed": request_limit_info.get("voiceTokensUsedSinceLastRefresh", 0)
                        },
                        "codebase": {
                            "isUnlimited": request_limit_info.get("isUnlimitedCodebaseIndices", False),
                            "maxIndices": request_limit_info.get("maxCodebaseIndices", 0),
                            "maxFilesPerRepo": request_limit_info.get("maxFilesPerRepo", 0)
                        }
                    }
                elif user_data.get("__typename") == "UserFacingError":
                    error = user_data.get("error", {}).get("message", "Unknown error")
                    print(f"❌ 获取额度失败: {error}")
                    return {"success": False, "error": error}
                else:
                    print(f"❌ 响应中没有找到用户信息")
                    return {"success": False, "error": "未找到用户信息"}
            else:
                error_text = response.text[:500]
                print(f"❌ HTTP错误 {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}: {error_text}"}

        except Exception as e:
            print(f"❌ 获取额度错误: {e}")
            return {"success": False, "error": str(e)}


# ==================== 注册监控器 ====================
class RegistrationMonitor:
    """注册监控器"""

    def __init__(self, target_accounts: int = config.TARGET_ACCOUNTS, max_concurrent: int = config.MAX_CONCURRENT_REGISTER):
        self.target_accounts = target_accounts
        self.max_concurrent = max_concurrent
        self.db_manager = AsyncDatabaseManager()
        self.proxy_manager = AsyncProxyManager()
        self.running = False
        self.stats = {
            "total_attempts": 0,
            "successful": 0,
            "failed": 0
        }
        self.stats_lock = asyncio.Lock()
        self.outlook_client = OutlookAPIClient(
            config.OUTLOOK_API_CONFIG["app_id"],
            config.OUTLOOK_API_CONFIG["app_key"]
        )

    async def buy_outlook_email(self) -> Optional[Dict]:
        """购买Outlook邮箱"""
        result = await self.outlook_client.get_email(config.OUTLOOK_API_CONFIG["commodity_id"], 1)

        if result.get('code') == 200 and result.get('data'):
            cards = result['data'].get('cards', [])
            if cards:
                card_info = cards[0]
                parts = card_info.split('----')
                if len(parts) >= 4:
                    return {
                        'email': parts[0],
                        'email_password': parts[1],
                        'client_id': parts[2],
                        'refresh_token': parts[3]
                    }

        return None

    async def registration_worker(self, worker_id: int):
        """异步注册工作函数"""
        logger.info(f"🚀 工作线程 {worker_id} 已启动")

        while self.running:
            try:
                # 检查当前账户数量
                current_count = await self.db_manager.get_account_count('active')
                if current_count >= self.target_accounts:
                    logger.info(f"[Worker-{worker_id}] 已达到目标账户数 ({current_count}/{self.target_accounts})")
                    await asyncio.sleep(30)
                    continue

                # 购买邮箱
                logger.info(f"[Worker-{worker_id}] 购买邮箱...")
                email_info = await self.buy_outlook_email()

                if not email_info:
                    logger.error(f"[Worker-{worker_id}] 购买邮箱失败")
                    async with self.stats_lock:
                        self.stats["failed"] += 1
                    await asyncio.sleep(30)
                    continue

                logger.info(f"[Worker-{worker_id}] 成功购买邮箱: {email_info['email']}")

                # 创建注册机器人并执行注册
                bot = WarpRegistrationBot(self.db_manager, self.proxy_manager)
                local_id = await bot.register_account(email_info)

                async with self.stats_lock:
                    self.stats["total_attempts"] += 1

                if local_id:
                    async with self.stats_lock:
                        self.stats["successful"] += 1
                    logger.info(f"[Worker-{worker_id}] ✅ 注册成功: {email_info['email']}")
                    await asyncio.sleep(5)
                else:
                    async with self.stats_lock:
                        self.stats["failed"] += 1
                    logger.error(f"[Worker-{worker_id}] ❌ 注册失败: {email_info['email']}")
                    await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 工作线程异常: {e}")
                async with self.stats_lock:
                    self.stats["failed"] += 1
                await asyncio.sleep(10)

        logger.info(f"🛑 工作线程 {worker_id} 已停止")

    async def print_stats(self):
        """定期打印统计信息"""
        while self.running:
            await asyncio.sleep(30)

            async with self.stats_lock:
                stats = self.stats.copy()

            active_count = await self.db_manager.get_account_count('active')

            logger.info("=" * 50)
            logger.info(f"📊 注册统计")
            logger.info(f"🎯 目标账户数: {self.target_accounts}")
            logger.info(f"✅ 当前活跃账户: {active_count}")
            logger.info(
                f"📈 进度: {active_count}/{self.target_accounts} ({active_count / self.target_accounts * 100:.1f}%)")
            logger.info(f"🔄 总尝试次数: {stats['total_attempts']}")
            logger.info(f"✅ 成功: {stats['successful']}")
            logger.info(f"❌ 失败: {stats['failed']}")
            if stats['total_attempts'] > 0:
                success_rate = stats['successful'] / stats['total_attempts'] * 100
                logger.info(f"📊 成功率: {success_rate:.1f}%")
            logger.info("=" * 50)

    async def start(self):
        """启动监控器"""

        # 初始化Outlook客户端
        await self.outlook_client._ensure_client()

        self.running = True

        # 创建工作任务
        tasks = []
        for i in range(self.max_concurrent):
            task = asyncio.create_task(self.registration_worker(i + 1))
            tasks.append(task)

        # 添加统计任务
        stats_task = asyncio.create_task(self.print_stats())
        tasks.append(stats_task)

        logger.info(f"✅ 启动了 {self.max_concurrent} 个工作线程")

        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("⌨️ 收到停止信号")
        finally:
            self.running = False
            await self.outlook_client.close()


# ==================== 主函数 ====================
async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🚀 Warp账号注册脚本启动")
    logger.info(f"📊 目标账号数: {config.TARGET_ACCOUNTS}")
    logger.info(f"⚡ 最大并发数: {config.MAX_CONCURRENT_REGISTER}")
    logger.info("=" * 60)

    monitor = RegistrationMonitor(
        target_accounts=config.TARGET_ACCOUNTS,
        max_concurrent=config.MAX_CONCURRENT_REGISTER
    )

    await monitor.start()

    logger.info("✅ 注册任务完成")


if __name__ == "__main__":
    asyncio.run(main())
