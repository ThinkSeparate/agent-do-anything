#!/usr/bin/env python3
"""
日志自动转存脚本

功能：
1. 只保留最新的5个日志文件在原目录
2. 其他的按年月分目录转存到 logs/archive/
3. 生成转存索引

使用：
    python archive_logs.py [options]

选项：
    --dry-run       预览模式，不实际执行
    --keep N        保留最新N个日志（默认：5）
    --list          列出转存统计
"""

import os
import shutil
import argparse
from datetime import datetime
from pathlib import Path
import json

# 配置
LOG_DIRS = [
    ("logs/agent", "logs/archive/agent"),
    ("logs/conv", "logs/archive/conv")
]
INDEX_FILE = "logs/archive_index.json"
KEEP_COUNT = 5  # 保留最新5个


def parse_log_date(filename: str) -> datetime:
    """从日志文件名解析日期: agent_20260402_203804.log -> datetime"""
    try:
        parts = filename.replace('.log', '').split('_')
        if len(parts) >= 3:
            date_str = parts[1]  # 20260402
            time_str = parts[2]  # 203804
            return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        pass
    return datetime.fromtimestamp(0)


def load_index() -> dict:
    """加载转存索引"""
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"archives": [], "last_run": None}


def save_index(index: dict):
    """保存转存索引"""
    index["last_run"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def archive_logs(dry_run: bool = False, keep_count: int = KEEP_COUNT):
    """执行日志转存"""
    index = load_index()
    total_moved = 0
    total_bytes = 0

    print(f"日志转存任务")
    print(f"  保留数量: 最新 {keep_count} 个")
    if dry_run:
        print("  [预览模式] 不会实际执行")
    print("-" * 60)

    for src_dir, archive_base in LOG_DIRS:
        if not os.path.exists(src_dir):
            continue

        # 收集所有日志文件
        log_files = []
        for f in os.listdir(src_dir):
            if f.endswith('.log'):
                filepath = Path(src_dir) / f
                file_date = parse_log_date(f)
                log_files.append((filepath, file_date, f))

        # 按日期排序（新的在前）
        log_files.sort(key=lambda x: x[1], reverse=True)

        to_keep = log_files[:keep_count]
        to_archive = log_files[keep_count:]

        if not to_archive:
            print(f"\n{src_dir}: 无需转存（共{len(log_files)}个）")
            continue

        print(f"\n{src_dir}:")
        print(f"  保留: {len(to_keep)} 个")
        print(f"  转存: {len(to_archive)} 个")

        for filepath, file_date, filename in to_archive:
            # 按年月创建子目录: logs/archive/conv/202604/
            year_month = file_date.strftime("%Y%m")
            archive_dir = os.path.join(archive_base, year_month)
            dst_path = Path(archive_dir) / filename

            if dry_run:
                print(f"  [预览] 将转存: {filename} -> {archive_dir}/")
                continue

            # 执行转存
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(str(filepath), str(dst_path))

            file_size = dst_path.stat().st_size
            total_bytes += file_size
            total_moved += 1

            # 记录索引
            index["archives"].append({
                "original": str(filepath),
                "archived": str(dst_path),
                "date": file_date.isoformat(),
                "size": file_size
            })
            print(f"  ✓ 已转存: {filename}")

    if not dry_run and total_moved > 0:
        save_index(index)

    print("\n" + "=" * 60)
    print("转存完成")
    print(f"  转存文件: {total_moved} 个")
    print(f"  总大小: {total_bytes / 1024 / 1024:.2f} MB")
    print(f"  索引文件: {INDEX_FILE}")


def list_archives():
    """列出转存统计"""
    if not os.path.exists(INDEX_FILE):
        print("没有找到转存索引")
        return

    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        index = json.load(f)

    archives = index.get("archives", [])

    # 按目录和月份统计
    by_location = {}
    for item in archives:
        archived_path = item["archived"]
        # 提取 archive/conv/202604 部分
        parts = archived_path.split(os.sep)
        if len(parts) >= 3:
            key = f"{parts[-3]}/{parts[-2]}/{parts[-1][:6]}"  # archive/conv/202604
        else:
            key = "其他"

        if key not in by_location:
            by_location[key] = {"count": 0, "size": 0}
        by_location[key]["count"] += 1
        by_location[key]["size"] += item.get("size", 0)

    print("转存统计:")
    print("-" * 60)
    total_files = 0
    total_size = 0
    for key in sorted(by_location.keys()):
        stats = by_location[key]
        total_files += stats["count"]
        total_size += stats["size"]
        print(f"  {key}: {stats['count']} 个文件, {stats['size']/1024/1024:.2f} MB")

    print("-" * 60)
    print(f"总计: {total_files} 个文件, {total_size/1024/1024:.2f} MB")
    print(f"最后运行: {index.get('last_run', 'N/A')}")


def main():
    parser = argparse.ArgumentParser(description='日志自动转存脚本')
    parser.add_argument('--dry-run', action='store_true', help='预览模式')
    parser.add_argument('--keep', type=int, default=KEEP_COUNT, help=f'保留最新N个（默认：{KEEP_COUNT}）')
    parser.add_argument('--list', action='store_true', help='列出转存统计')

    args = parser.parse_args()

    if args.list:
        list_archives()
    else:
        archive_logs(dry_run=args.dry_run, keep_count=args.keep)


if __name__ == "__main__":
    main()
