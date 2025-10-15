#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移：添加credits相关字段
"""

import sqlite3
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def migrate_database(db_path: str = config.DATABASE_PATH):
    """添加credits相关字段"""
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(accounts)")
        columns = [row[1] for row in cursor.fetchall()]
        
        migrations = []
        
        if 'request_limit' not in columns:
            migrations.append(('request_limit', 'INTEGER DEFAULT 0', '请求额度上限'))
        
        if 'requests_used' not in columns:
            migrations.append(('requests_used', 'INTEGER DEFAULT 0', '已使用请求数'))
        
        if 'requests_remaining' not in columns:
            migrations.append(('requests_remaining', 'INTEGER DEFAULT 0', '剩余请求数'))
        
        if 'is_unlimited' not in columns:
            migrations.append(('is_unlimited', 'INTEGER DEFAULT 0', '是否无限额度(0/1)'))
        
        if 'quota_type' not in columns:
            migrations.append(('quota_type', 'TEXT DEFAULT "normal"', '额度类型(unlimited/high/normal)'))
        
        if 'next_refresh_time' not in columns:
            migrations.append(('next_refresh_time', 'TIMESTAMP', '下次刷新时间'))
        
        if 'refresh_duration' not in columns:
            migrations.append(('refresh_duration', 'TEXT DEFAULT "WEEKLY"', '刷新周期'))
        
        if 'credits_updated_at' not in columns:
            migrations.append(('credits_updated_at', 'TIMESTAMP', 'credits更新时间'))
        
        if not migrations:
            print("✅ 所有字段已存在，无需迁移")
            conn.close()
            return True
        
        # 执行迁移
        print(f"🔄 开始迁移，共 {len(migrations)} 个字段...")
        
        for field_name, field_type, description in migrations:
            sql = f"ALTER TABLE accounts ADD COLUMN {field_name} {field_type}"
            cursor.execute(sql)
            print(f"   ✅ 已添加字段: {field_name} - {description}")
        
        conn.commit()
        conn.close()
        
        print(f"✅ 数据库迁移完成！共添加 {len(migrations)} 个字段")
        return True
        
    except Exception as e:
        print(f"❌ 数据库迁移失败: {e}")
        return False


if __name__ == "__main__":
    migrate_database()
