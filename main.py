#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp 服务统一启动器
"""

import multiprocessing
import time
import sys
import os
import importlib
import logging
import asyncio
from pathlib import Path

# 在导入项目模块之前，确保项目根目录在sys.path中
# 这有助于解决在不同环境下模块导入失败的问题
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import config

# 配置日志
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)


# ==================== 数据库初始化检查 ====================

def check_and_init_database():
    """检查数据库是否存在，不存在则自动初始化"""
    db_path = Path(config.DATABASE_PATH)

    if db_path.exists():
        logger.info(f"✅ 数据库已存在: {config.DATABASE_PATH}")
        return True

    logger.warning(f"⚠️  数据库不存在: {config.DATABASE_PATH}")
    logger.info("🔨 开始自动初始化数据库...")

    try:
        # 导入初始化模块
        init_db = importlib.import_module("init_database")

        # 执行初始化
        success = init_db.init_database(config.DATABASE_PATH, force=False)

        if success:
            logger.info("✅ 数据库初始化成功")
            return True
        else:
            logger.error("❌ 数据库初始化失败")
            return False

    except Exception as e:
        logger.error(f"❌ 数据库初始化异常: {e}", exc_info=True)
        return False


# ==================== 服务启动函数 ====================

def run_server():
    """启动 Protobuf 主服务 (server.py)"""
    logger.info("正在启动 Protobuf 主服务...")
    try:
        # 动态导入并执行main函数
        module = importlib.import_module("server")
        module.main()
    except Exception as e:
        logger.error(f"Protobuf 主服务启动失败: {e}", exc_info=True)


def run_openai_compat():
    """启动 OpenAI 兼容服务 (openai_compat.py)"""
    logger.info("正在启动 OpenAI 兼容服务...")
    try:
        # openai_compat.py 使用 uvicorn.run 并且没有main函数
        # 我们需要模拟它的 __main__ 执行块
        module = importlib.import_module("openai_compat")
        uvicorn = importlib.import_module("uvicorn")
        
        # 刷新JWT
        try:
            from warp2protobuf.core.auth import refresh_jwt_if_needed as _refresh_jwt
            asyncio.run(_refresh_jwt())
        except Exception:
            pass
            
        uvicorn.run(
            module.app,
            host=config.OPENAI_COMPAT_HOST,
            port=config.OPENAI_COMPAT_PORT,
            log_level=config.LOG_LEVEL.lower(),
        )
    except Exception as e:
        logger.error(f"OpenAI 兼容服务启动失败: {e}", exc_info=True)


def run_pool_service():
    """启动账号池HTTP服务 (pool_service.py)"""
    logger.info("正在启动账号池HTTP服务...")
    try:
        module = importlib.import_module("pool_service")
        asyncio.run(module.main())
    except Exception as e:
        logger.error(f"账号池HTTP服务启动失败: {e}", exc_info=True)


def run_pool_maintenance():
    """启动账号池维护脚本 (pool_maintenance.py)"""
    logger.info("正在启动账号池维护脚本...")
    try:
        module = importlib.import_module("pool_maintenance")
        # 默认以 'auto' 模式运行
        sys.argv = [sys.argv[0], 'auto']
        asyncio.run(module.main())
    except Exception as e:
        logger.error(f"账号池维护脚本启动失败: {e}", exc_info=True)


def run_warp_register():
    """启动Warp账号注册脚本 (warp_register.py)"""
    logger.info("正在启动Warp账号注册脚本...")
    try:
        module = importlib.import_module("warp_register")
        asyncio.run(module.main())
    except Exception as e:
        logger.error(f"Warp账号注册脚本启动失败: {e}", exc_info=True)


# ==================== 进程管理 ====================

SERVICES = {
    "server": run_server,
    "openai": run_openai_compat,
    "pool_maintenance": run_pool_maintenance,
    "register": run_warp_register,
}

# 独立服务（仅用于调试，不在"all"模式中启动）
STANDALONE_SERVICES = {
    "pool_service": run_pool_service,  # 账号池已集成到server，独立运行仅用于调试
}


def start_all_services():
    """启动所有服务"""
    # 在启动服务前检查并初始化数据库
    logger.info("=" * 60)
    logger.info("🔍 检查数据库状态...")
    logger.info("=" * 60)

    if not check_and_init_database():
        logger.error("❌ 数据库初始化失败，无法启动服务")
        logger.error("请检查错误信息或手动运行: python init_database.py")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("🚀 开始启动所有服务...")
    logger.info("=" * 60)

    processes = []
    for name, target_func in SERVICES.items():
        process = multiprocessing.Process(target=target_func, name=f"Process-{name}")
        processes.append(process)
        process.start()
        logger.info(f"服务 '{name}' 已在进程 {process.pid} 中启动。")

    try:
        while True:
            time.sleep(1)
            for process in processes:
                if not process.is_alive():
                    logger.warning(f"进程 '{process.name}' (PID: {process.pid}) 已退出。")
                    # 可选择在这里添加重启逻辑
                    processes.remove(process)

            if not processes:
                logger.info("所有服务进程都已退出。")
                break

    except KeyboardInterrupt:
        logger.info("接收到停止信号，正在关闭所有服务...")
        for process in processes:
            process.terminate()
            process.join()
        logger.info("所有服务已停止。")


def print_usage():
    """打印使用说明"""
    print("=" * 60)
    print("Warp 服务统一启动器 (优化版)")
    print("=" * 60)
    print("用法:")
    print("  python main.py [命令]")
    print("\n🚀 主要命令:")
    print("  all                - 启动所有服务 (推荐)")
    print("")
    print("📋 核心服务:")
    for name in SERVICES:
        desc = {
            "server": "Protobuf主服务+账号池 (8000端口)",
            "openai": "OpenAI兼容接口 (8010端口)", 
            "pool_maintenance": "账号池维护脚本",
            "register": "Warp账号注册脚本"
        }.get(name, f"{name} 服务")
        print(f"  {name:<18} - {desc}")
    print("")
    print("🔧 调试服务:")
    for name in STANDALONE_SERVICES:
        desc = {
            "pool_service": "独立账号池服务 (8019端口，仅调试用)"
        }.get(name, f"{name} 服务")
        print(f"  {name:<18} - {desc}")
    print("")
    print("💡 优化说明:")
    print("  - 账号池功能已集成到8000端口，无需独立运行")
    print("  - 'all'模式不再启动独立的pool_service避免冲突")
    print("")
    print("示例:")
    print("  python main.py all         # 启动优化后的服务")
    print("  python main.py server      # 仅启动主服务(含账号池)")
    print("  python main.py pool_service # 调试模式：独立账号池服务")
    print("=" * 60)


if __name__ == "__main__":
    # 设置多进程启动方式，这对于Windows和macOS是推荐的
    multiprocessing.set_start_method("spawn", force=True)

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "all":
        start_all_services()
    elif command in SERVICES:
        logger.info(f"以调试模式启动核心服务: '{command}'")
        SERVICES[command]()
    elif command in STANDALONE_SERVICES:
        logger.info(f"以调试模式启动独立服务: '{command}'")
        STANDALONE_SERVICES[command]()
    else:
        print(f"错误: 未知命令 '{command}'\n")
        print_usage()
        sys.exit(1)