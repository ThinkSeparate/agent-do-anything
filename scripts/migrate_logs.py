#!/usr/bin/env python3
"""
迁移旧日志文件到新目录结构。
保留最新的日志文件（可能正在被写入），迁移其他文件。
"""
import os
import glob
import shutil
import sys


def migrate_logs(project_dir=None):
    """迁移旧日志文件到 logs/agent/ 和 logs/conv/ 目录"""
    if project_dir is None:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    log_dir = os.path.join(project_dir, 'logs')
    if not os.path.exists(log_dir):
        print("日志目录不存在，无需迁移")
        return

    agent_log_dir = os.path.join(log_dir, 'agent')
    conv_log_dir = os.path.join(log_dir, 'conv')

    os.makedirs(agent_log_dir, exist_ok=True)
    os.makedirs(conv_log_dir, exist_ok=True)

    # 获取所有agent日志文件
    agent_files = glob.glob(os.path.join(log_dir, 'agent_*.log'))
    conv_files = glob.glob(os.path.join(log_dir, 'conv_*.log'))

    # 按文件名排序（时间戳格式确保最新在后面）
    agent_files.sort()
    conv_files.sort()

    migrated_count = 0

    # 迁移agent日志（保留最新的一个）
    for f in agent_files[:-1] if len(agent_files) > 1 else []:
        try:
            dest = os.path.join(agent_log_dir, os.path.basename(f))
            shutil.move(f, dest)
            print(f"已迁移: {os.path.basename(f)} -> logs/agent/")
            migrated_count += 1
        except Exception as e:
            print(f"迁移失败 {os.path.basename(f)}: {e}")

    # 迁移conv日志（保留最新的一个）
    for f in conv_files[:-1] if len(conv_files) > 1 else []:
        try:
            dest = os.path.join(conv_log_dir, os.path.basename(f))
            shutil.move(f, dest)
            print(f"已迁移: {os.path.basename(f)} -> logs/conv/")
            migrated_count += 1
        except Exception as e:
            print(f"迁移失败 {os.path.basename(f)}: {e}")

    if migrated_count == 0:
        print("没有需要迁移的日志文件（已是最新结构或只有最新日志）")
    else:
        print(f"\n迁移完成，共迁移 {migrated_count} 个文件")
        print(f"保留最新日志未动（可能正在被程序使用）")


if __name__ == "__main__":
    project_dir = sys.argv[1] if len(sys.argv) > 1 else None
    migrate_logs(project_dir)
