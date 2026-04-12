#!/usr/bin/env python3
"""
清理数据库中重复的任务记录。

规则：相同 original_task 描述的任务，只保留 session_id 最大（最新）的一条，删除其他旧的。

使用方法:
    python scripts/cleanup_duplicate_tasks.py         # 查看将要删除的记录（预览模式）
    python scripts/cleanup_duplicate_tasks.py --exec  # 执行实际删除
"""

import sqlite3
import sys
from pathlib import Path


def get_db_path() -> str:
    """获取数据库路径"""
    # 脚本在 scripts 目录下，数据库在项目根目录
    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent
    return str(project_dir / ".session_states.db")


def preview_duplicates(db_path: str) -> dict:
    """预览将要删除的重复任务，返回统计信息"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 查找有重复的任务描述
    cursor = conn.execute("""
        SELECT original_task, COUNT(*) as cnt, MAX(session_id) as latest_id
        FROM session_states
        GROUP BY original_task
        HAVING cnt > 1
    """)
    duplicates = cursor.fetchall()

    total_duplicates = len(duplicates)
    total_to_delete = 0

    if total_duplicates == 0:
        print("没有发现重复任务。")
        conn.close()
        return {"total_duplicates": 0, "total_to_delete": 0, "total_kept": 0}

    print(f"发现 {total_duplicates} 个重复任务描述：\n")
    print("=" * 80)

    for row in duplicates:
        task = row["original_task"]
        count = row["cnt"]
        latest_id = row["latest_id"]
        to_delete = count - 1
        total_to_delete += to_delete

        # 显示任务预览
        preview = task[:60] + "..." if len(task) > 60 else task
        print(f"\n任务描述: {preview}")
        print(f"  重复次数: {count}")
        print(f"  保留: session_id={latest_id}")
        print(f"  将删除: {to_delete} 条旧记录")

        # 列出将要删除的具体记录
        cursor = conn.execute("""
            SELECT session_id, status, created_at
            FROM session_states
            WHERE original_task = ? AND session_id != ?
            ORDER BY session_id ASC
        """, (task, latest_id))
        old_records = cursor.fetchall()

        for record in old_records:
            print(f"    - session_id={record['session_id']}, status={record['status']}, created={record['created_at']}")

    print("\n" + "=" * 80)

    # 统计总数
    cursor = conn.execute("SELECT COUNT(*) FROM session_states")
    total_before = cursor.fetchone()[0]
    total_after = total_before - total_to_delete

    print(f"\n总计:")
    print(f"  当前记录数: {total_before}")
    print(f"  将删除: {total_to_delete} 条")
    print(f"  保留: {total_after} 条")

    conn.close()

    return {
        "total_duplicates": total_duplicates,
        "total_to_delete": total_to_delete,
        "total_kept": total_after
    }


def execute_cleanup(db_path: str) -> dict:
    """执行清理操作"""
    conn = sqlite3.connect(db_path)

    # 获取删除前的统计
    cursor = conn.execute("SELECT COUNT(*) FROM session_states")
    total_before = cursor.fetchone()[0]

    # 删除重复的旧记录（保留每个 original_task 的最新一条）
    cursor = conn.execute("""
        DELETE FROM session_states
        WHERE session_id NOT IN (
            SELECT MAX(session_id)
            FROM session_states
            GROUP BY original_task
        )
    """)
    deleted_count = cursor.rowcount
    conn.commit()

    # 获取删除后的统计
    cursor = conn.execute("SELECT COUNT(*) FROM session_states")
    total_after = cursor.fetchone()[0]

    conn.close()

    return {
        "total_before": total_before,
        "deleted": deleted_count,
        "total_after": total_after
    }


def main():
    db_path = get_db_path()

    if not Path(db_path).exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        sys.exit(1)

    print(f"数据库路径: {db_path}\n")

    # 检查参数
    exec_mode = "--exec" in sys.argv or "-e" in sys.argv
    force_mode = "--force" in sys.argv or "-f" in sys.argv

    if not exec_mode:
        # 预览模式
        print("【预览模式】以下是将要被删除的重复任务：\n")
        stats = preview_duplicates(db_path)

        if stats["total_duplicates"] > 0:
            print(f"\n要执行实际删除，请运行:")
            print(f"  python {sys.argv[0]} --exec")
    else:
        # 执行模式
        print("【执行模式】正在清理重复任务...\n")

        # 先预览
        preview_stats = preview_duplicates(db_path)

        if preview_stats["total_to_delete"] == 0:
            print("\n没有需要删除的记录。")
            sys.exit(0)

        # 确认执行（除非使用 --force）
        if not force_mode:
            try:
                print(f"\n确认删除 {preview_stats['total_to_delete']} 条记录? (yes/no): ", end="")
                confirm = input().strip().lower()

                if confirm not in ["yes", "y", "是"]:
                    print("已取消操作。")
                    sys.exit(0)
            except EOFError:
                print("\n错误: 无法读取输入。如需自动确认，请使用 --force 参数")
                print(f"  python {sys.argv[0]} --exec --force")
                sys.exit(1)

        # 执行删除
        result = execute_cleanup(db_path)

        print(f"\n清理完成!")
        print(f"  删除前: {result['total_before']} 条")
        print(f"  已删除: {result['deleted']} 条")
        print(f"  剩余: {result['total_after']} 条")


if __name__ == "__main__":
    main()
