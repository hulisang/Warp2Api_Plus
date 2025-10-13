# test_pool_api.py
import httpx
import asyncio
import json


# 测试账号池服务连接
async def test_pool_service():
    base_url = "http://localhost:8019"

    async with httpx.AsyncClient() as client:
        # 1. 测试根路径
        try:
            resp = await client.get(base_url, timeout=5)
            print(f"根路径测试: {resp.status_code}")
            print(f"响应: {resp.json()}")
        except Exception as e:
            print(f"根路径测试失败: {e}")

        # 2. 测试状态接口
        try:
            resp = await client.get(f"{base_url}/api/status", timeout=5)
            print(f"\n状态接口测试: {resp.status_code}")
            print(f"响应: {json.dumps(resp.json(), indent=2)}")
        except Exception as e:
            print(f"状态接口测试失败: {e}")

        # 3. 测试分配账号
        try:
            resp = await client.post(
                f"{base_url}/api/accounts/allocate",
                json={"count": 1, "session_duration": 1800},
                timeout=10
            )
            print(f"\n分配账号测试: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"成功分配，会话ID: {data.get('session_id')}")
                print(f"账号数量: {len(data.get('accounts', []))}")
            else:
                print(f"分配失败: {resp.text}")
        except Exception as e:
            print(f"分配账号测试失败: {e}")


async def main():
    await test_pool_service()


if __name__ == "__main__":
    asyncio.run(main())
