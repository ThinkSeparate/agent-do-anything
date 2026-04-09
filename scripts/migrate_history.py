#!/usr/bin/env python
"""迁移历史任务从 JSON 到 SQLite 数据库"""

import json
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.session_persistence import SessionPersistence


def migrate_task_history(project_dir: str):
    """将 task_history.json 中的任务迁移到 SQLite 数据库"""

    json_path = os.path.join(project_dir, "task_history.json")
    if not os.path.exists(json_path):
        print(f"未找到 {json_path}，跳过迁移")
        return

    # 读取 JSON 历史记录
    with open(json_path, 'r', encoding='utf-8') as f:
        history = json.load(f)

    if not history:
        print("JSON 历史记录为空，无需迁移")
        return

    # 初始化持久化层
    persistence = SessionPersistence(project_dir)

    # 去重：按 task 内容去重，保留最早的 timestamp
    seen_tasks = {}
    for task_id, record in history.items():
        task_content = record.get("task", "").strip()
        if not task_content:
            continue

        timestamp = record.get("timestamp", "")

        # 如果 task 内容已存在，保留较早的那个
        if task_content in seen_tasks:
            existing_ts = seen_tasks[task_content].get("timestamp", "")
            if timestamp and existing_ts:
                try:
                    if timestamp < existing_ts:
                        seen_tasks[task_content] = record
                except:
                    pass
            continue

        seen_tasks[task_content] = record

    print(f"JSON 中共有 {len(history)} 条记录，去重后 {len(seen_tasks)} 条")

    # 查询数据库中已有的任务（避免重复插入）
    existing_sessions = persistence.list_sessions(limit=1000)
    existing_tasks = set()
    for session in existing_sessions:
        task = session.get("original_task", "").strip()
        if task:
            existing_tasks.add(task)

    print(f"数据库中已有 {len(existing_tasks)} 条任务记录")

    # 插入新任务
    inserted_count = 0
    skipped_count = 0

    for task_content, record in seen_tasks.items():
        # 跳过已存在的
        if task_content in existing_tasks:
            skipped_count += 1
            continue

        # 创建会话并直接标记为 completed（这些是历史遗留任务，无执行记录）
        session_id = persistence.create_session(task_content)
        persistence.mark_completed(session_id)

        inserted_count += 1
        print(f"  已迁移: {task_content[:50]}...")

    print(f"\n迁移完成:")
    print(f"  - 插入新任务: {inserted_count}")
    print(f"  - 跳过已存在: {skipped_count}")

    # 建议删除旧文件
    print(f"\n可以安全删除旧文件: {json_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        project_dir = sys.argv[1]
    else:
        project_dir = project_root

    migrate_task_history(project_dir)
