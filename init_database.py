#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本
用于创建 warp_accounts.db 数据库及其完整表结构
"""

import sqlite3
import sys
import os
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def init_database(db_path: str = config.DATABASE_PATH, force: bool = False):
    """
    初始化数据库
    
    Args:
        db_path: 数据库文件路径
        force: 是否强制重新创建（会删除现有数据库）
    """
    
    db_file = Path(db_path)
    
    # 检查数据库是否已存在
    if db_file.exists():
        if not force:
            print(f"⚠️  数据库文件已存在: {db_path}")
            print("   如果需要重新创建，请使用 --force 参数")
            print("   警告：使用 --force 会删除所有现有数据！")
            return False
        else:
            print(f"🗑️  删除现有数据库: {db_path}")
            db_file.unlink()
    
    print(f"🔨 开始创建数据库: {db_path}")
    
    try:
        # 连接数据库（会自动创建文件）
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 创建 accounts 表
        print("📋 创建 accounts 表...")
        cursor.execute('''
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                email_password TEXT,
                local_id TEXT NOT NULL,
                id_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                client_id TEXT,
                outlook_refresh_token TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proxy_info TEXT,
                user_agent TEXT,
                last_refresh_time TIMESTAMP,
                last_used TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                last_error TEXT,
                error_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                request_limit INTEGER DEFAULT 0,
                requests_used INTEGER DEFAULT 0,
                requests_remaining INTEGER DEFAULT 0,
                is_unlimited INTEGER DEFAULT 0,
                quota_type TEXT DEFAULT "normal",
                next_refresh_time TIMESTAMP,
                refresh_duration TEXT DEFAULT "WEEKLY",
                credits_updated_at TIMESTAMP
            )
        ''')
        print("   ✅ accounts 表创建成功")
        
        # 创建索引
        print("🔍 创建索引...")
        
        # 状态索引
        cursor.execute('''
            CREATE INDEX idx_status 
            ON accounts (status)
        ''')
        print("   ✅ idx_status 创建成功")
        
        # 最后刷新时间索引
        cursor.execute('''
            CREATE INDEX idx_last_refresh 
            ON accounts (last_refresh_time)
        ''')
        print("   ✅ idx_last_refresh 创建成功")
        
        # 状态+最后使用时间复合索引
        cursor.execute('''
            CREATE INDEX idx_accounts_status_last_used 
            ON accounts (status, last_used)
        ''')
        print("   ✅ idx_accounts_status_last_used 创建成功")
        
        # 邮箱唯一索引
        cursor.execute('''
            CREATE UNIQUE INDEX idx_accounts_email 
            ON accounts (email)
        ''')
        print("   ✅ idx_accounts_email 创建成功")
        
        # 状态+邮箱复合索引
        cursor.execute('''
            CREATE INDEX idx_accounts_status_email 
            ON accounts (status, email)
        ''')
        print("   ✅ idx_accounts_status_email 创建成功")
        
        # 优化数据库设置
        print("⚙️  配置数据库优化参数...")
        cursor.execute("PRAGMA journal_mode = WAL")  # 使用WAL模式，提升并发性能
        cursor.execute("PRAGMA synchronous = NORMAL")  # 平衡性能和安全性
        cursor.execute("PRAGMA cache_size = 10000")  # 增加缓存大小
        cursor.execute("PRAGMA temp_store = MEMORY")  # 使用内存存储临时数据
        print("   ✅ 数据库优化配置完成")
        
        # 提交更改
        conn.commit()
        conn.close()
        
        print("=" * 60)
        print("✅ 数据库初始化完成！")
        print(f"📁 数据库路径: {db_path}")
        print("=" * 60)
        print("\n📝 表结构说明:")
        print("   - accounts: 存储Warp账号信息")
        print("     * 核心字段: email, local_id, id_token, refresh_token")
        print("     * 状态管理: status, created_at, last_used, use_count")
        print("     * Credits: request_limit, requests_used, quota_type")
        print("     * 代理信息: proxy_info, user_agent")
        print("\n🔍 已创建索引:")
        print("   - idx_status: 按状态查询")
        print("   - idx_last_refresh: 按刷新时间查询")
        print("   - idx_accounts_status_last_used: 按状态+使用时间查询")
        print("   - idx_accounts_email: 邮箱唯一索引")
        print("   - idx_accounts_status_email: 按状态+邮箱查询")
        print("\n⚡ 性能优化:")
        print("   - WAL模式: 提升并发读写性能")
        print("   - 缓存优化: 10000页缓存")
        print("   - 内存临时存储: 加速临时操作")
        print("\n🚀 下一步:")
        print("   1. 运行 python main.py all 启动所有服务")
        print("   2. 或访问 http://localhost:8019/pool.html 管理账号池")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_database(db_path: str = config.DATABASE_PATH):
    """
    验证数据库结构
    
    Args:
        db_path: 数据库文件路径
    """
    
    if not Path(db_path).exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"🔍 验证数据库: {db_path}")
        print("=" * 60)
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        if not cursor.fetchone():
            print("❌ accounts 表不存在")
            conn.close()
            return False
        print("✅ accounts 表存在")
        
        # 检查字段
        cursor.execute("PRAGMA table_info(accounts)")
        columns = cursor.fetchall()
        print(f"✅ 表字段数量: {len(columns)}")
        
        expected_columns = [
            'id', 'email', 'email_password', 'local_id', 'id_token', 'refresh_token',
            'client_id', 'outlook_refresh_token', 'status', 'created_at', 'proxy_info',
            'user_agent', 'last_refresh_time', 'last_used', 'use_count', 'last_error',
            'error_count', 'updated_at', 'request_limit', 'requests_used',
            'requests_remaining', 'is_unlimited', 'quota_type', 'next_refresh_time',
            'refresh_duration', 'credits_updated_at'
        ]
        
        actual_columns = [col[1] for col in columns]
        missing_columns = set(expected_columns) - set(actual_columns)
        extra_columns = set(actual_columns) - set(expected_columns)
        
        if missing_columns:
            print(f"⚠️  缺少字段: {', '.join(missing_columns)}")
        if extra_columns:
            print(f"ℹ️  额外字段: {', '.join(extra_columns)}")
        
        if not missing_columns and not extra_columns:
            print("✅ 所有字段完整")
        
        # 检查索引
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='accounts'")
        indexes = cursor.fetchall()
        print(f"✅ 索引数量: {len(indexes)}")
        
        # 检查记录数
        cursor.execute("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        print(f"📊 账号数量: {count}")
        
        # 按状态统计
        cursor.execute("SELECT status, COUNT(*) FROM accounts GROUP BY status")
        status_counts = cursor.fetchall()
        if status_counts:
            print("📈 状态分布:")
            for status, cnt in status_counts:
                print(f"   - {status}: {cnt}")
        
        conn.close()
        
        print("=" * 60)
        print("✅ 数据库验证完成")
        return True
        
    except Exception as e:
        print(f"❌ 数据库验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Warp账号数据库初始化工具")
    parser.add_argument("--force", action="store_true", help="强制重新创建数据库（会删除现有数据）")
    parser.add_argument("--verify", action="store_true", help="验证数据库结构")
    parser.add_argument("--db", default=config.DATABASE_PATH, help="数据库文件路径")
    
    args = parser.parse_args()
    
    if args.verify:
        verify_database(args.db)
    else:
        init_database(args.db, args.force)

