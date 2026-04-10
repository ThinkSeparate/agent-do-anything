# utils/task_manager.py
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import logging

from utils.session_persistence import SessionPersistence


class TaskManager:
    """
    任务管理器，简化版交互流程
    """

    def __init__(self, project_directory: str, history_file: str = None):
        """
        初始化任务管理器

        Args:
            project_directory: 项目目录路径
            history_file: 任务历史文件名（保留兼容，但不再使用）
        """
        self.project_dir = project_directory
        self.persistence = SessionPersistence(project_directory)
        self.logger = logging.getLogger(__name__)
        self.current_task_id = None

    def get_task_input(self) -> Tuple[str, bool]:
        """
        获取任务输入（简化版）

        流程：
        1. 等待用户输入
        2. 如果是普通任务文本：询问是否保存，然后返回任务
        3. 如果是'h'：显示历史任务，然后等待输入编号
        4. 如果是历史编号：调用历史任务，二次确认后返回

        Returns:
            Tuple[str, bool]: (任务内容, 是否为历史任务)
        """
        print("\n" + "="*60)
        print("请输入任务 (输入 'h' 查看历史任务，输入 'q' 退出):")
        print("="*60)

        while True:
            # 第一步：获取初始输入
            user_input = input("\n> ").strip()

            if not user_input:
                print("输入不能为空，请重新输入")
                continue

            if user_input.lower() == 'q':
                return None, False

            # 情况1：查询历史任务
            if user_input.lower() == 'h':
                task = self._handle_history_mode()
                if task:
                    return task, True
                # 如果没有选择历史任务，继续等待输入
                continue

            # 情况2：尝试解析为历史任务编号
            if user_input.isdigit():
                task = self._handle_task_id_input(user_input)
                if task:
                    return task, True
                # 如果不是有效的任务编号，继续等待输入
                continue

            # 情况3：普通任务文本，自动保存
            self.save_task(user_input)
            return user_input, False

    def _handle_history_mode(self) -> Optional[str]:
        """处理历史任务查询模式，支持分页"""
        total_count = self.persistence.get_total_session_count()
        if total_count == 0:
            print("暂无历史任务")
            return None

        page_size = 20
        # 计算初始偏移量：显示最后 page_size 条（即最近的）
        offset = max(0, total_count - page_size)

        while True:
            # 加载当前页的任务
            tasks = self.persistence.list_sessions(limit=page_size, offset=offset)
            self._show_history_page(tasks, total_count, offset, page_size)

            # 显示操作提示
            print("\n" + "-"*60)
            print("操作:")
            print("  [编号] 选择对应任务")
            if offset > 0:
                print("  [p] 向上翻页（查看更早的）")
            if offset + page_size < total_count:
                print("  [n] 向下翻页（查看更新的）")
            print("  [a] 查看全部")
            print("  [回车] 返回")
            print("-"*60)

            choice = input("> ").strip()

            if not choice:
                return None  # 直接回车返回

            if choice.lower() == 'a':
                # 查看全部
                all_tasks = self.persistence.list_sessions(limit=1000, offset=0)
                self._show_history_page(all_tasks, total_count, 0, total_count)
                print("\n请输入历史任务编号调用任务，或按回车返回:")
                continue

            if choice.lower() == 'p' and offset > 0:
                # 向上翻页（显示更早的，即ID更小的）
                offset = max(0, offset - page_size)
                continue

            if choice.lower() == 'n' and offset + page_size < total_count:
                # 向下翻页（显示更新的，即ID更大的）
                offset = min(total_count - page_size, offset + page_size)
                continue

            if choice.isdigit():
                task_id = int(choice)
                task_record = self.get_task_by_id(task_id)

                if not task_record:
                    print(f"任务 ID {task_id} 不存在")
                    continue

                # 显示任务内容并直接返回
                task_content = task_record.get("original_task", "")
                status = task_record.get("status", "unknown")
                print("\n" + "="*60)
                print(f"历史任务 {task_id}:")
                print("="*60)
                print(f"状态: {status}")
                print(task_content)
                print("="*60)

                self.current_task_id = task_id
                return task_content

            print("无效输入，请重试")

    def _handle_task_id_input(self, input_str: str) -> Optional[str]:
        """处理任务编号输入"""
        task_id = int(input_str)
        task_record = self.get_task_by_id(task_id)

        if not task_record:
            # 不是有效的任务编号，可能用户想输入普通任务
            # 这里不返回，让上层继续处理
            return None

        # 显示任务内容并确认
        task_content = task_record.get("original_task", "")
        status = task_record.get("status", "unknown")
        print("\n" + "="*60)
        print(f"检测到历史任务 {task_id}:")
        print("="*60)
        print(f"状态: {status}")
        print(task_content)
        print("="*60)

        confirm = input("\n确认使用此历史任务？(y/n): ").strip().lower()
        if confirm in ['y', 'yes', '是']:
            self.current_task_id = task_id
            return task_content

        return None

    def _show_history_page(self, tasks: List[Dict[str, Any]], total_count: int, offset: int, page_size: int):
        """显示历史任务页面"""
        if not tasks:
            print("暂无历史任务")
            return

        start_id = tasks[0].get("session_id", "N/A") if tasks else "N/A"
        end_id = tasks[-1].get("session_id", "N/A") if tasks else "N/A"

        print("\n" + "="*80)
        print(f"历史任务列表 (共{total_count}个，显示ID {start_id}-{end_id})")
        print("="*80)

        for task_record in tasks:
            task_id = task_record.get("session_id", "N/A")
            task_content = task_record.get("original_task", "")
            status = task_record.get("status", "unknown")
            task_mode = task_record.get("task_mode", "short")
            created_at = task_record.get("created_at", "")

            # 格式化时间
            time_str = "未知时间"
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    pass

            # 显示任务预览
            preview = task_content[:50] + "..." if len(task_content) > 50 else task_content
            # 状态已经是4字符简写格式
            status_word = status[:4] if len(status) >= 4 else status.ljust(4)
            # 模式标识
            mode_indicator = "L" if task_mode == "long" else "S"

            print(f"[{task_id:3d}] [{status_word}] [{mode_indicator}] [{time_str}] {preview}")

        print("="*80)

    def save_task(self, task: str, result: str = None, **kwargs) -> int:
        """
        保存任务到历史记录，返回 session_id

        Args:
            task: 任务内容
            **kwargs: 额外信息，可包含 task_mode

        Returns:
            int: session_id，失败返回 -1
        """
        try:
            task_mode = kwargs.get('task_mode', 'short')
            session_id = self.persistence.create_session(task, task_mode=task_mode)
            self.current_task_id = session_id
            self.logger.info(f"任务已保存到历史记录，ID: {session_id}, 模式: {task_mode}",
                           extra={'tag': 'TASK_SAVED'})
            print(f"✓ 任务已保存，ID: {session_id} ({'长任务' if task_mode == 'long' else '短任务'})")
            return session_id
        except Exception as e:
            self.logger.error(f"保存任务失败: {str(e)}",
                            extra={'tag': 'TASK_SAVE_ERROR'})
            print(f"✗ 保存任务失败: {str(e)}")
            return -1

    def load_tasks(self) -> List[Dict[str, Any]]:
        """加载所有任务历史"""
        try:
            return self.persistence.list_sessions(limit=20)
        except Exception as e:
            self.logger.error(f"加载任务历史失败: {str(e)}")
            return []

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取任务"""
        try:
            return self.persistence.get_session(task_id)
        except Exception as e:
            self.logger.error(f"按ID获取任务失败: {str(e)}")
            return None

    def get_last_session(self) -> Optional[Dict[str, Any]]:
        """获取最近的会话"""
        return self.persistence.get_last_session()

    def delete_task(self, task_id: int) -> bool:
        """删除任务（暂不实现，或标记为 deleted）"""
        self.logger.warning(f"删除任务功能暂不可用，任务ID: {task_id}")
        return True
