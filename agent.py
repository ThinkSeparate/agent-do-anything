# agent.py (修改后的主函数部分 - 直接调用 ReAct Agent)
import os

os.environ['HTTP_PROXY'] = 'http://127.0.0.1:8080'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:8080'

# 方法2：指定mitmproxy证书路径（推荐，但需要先安装证书）
mitmproxy_cert_path = r"C:\Users\20785\.mitmproxy\mitmproxy-ca-cert.cer"
if os.path.exists(mitmproxy_cert_path):
    os.environ['REQUESTS_CA_BUNDLE'] = mitmproxy_cert_path
    os.environ['SSL_CERT_FILE'] = mitmproxy_cert_path
else:
    print(f"警告: mitmproxy证书未找到在 {mitmproxy_cert_path}")
    print("请访问 http://mitm.it/ 下载并安装证书")

import logging
from typing import Optional, Tuple
import click

from utils import setup_logging
from core.react.agent import ReActAgent
from utils.task_manager import TaskManager
from utils.user_profile import get_user_profile
from core.sandbox.config_ui import quick_setup_sandbox, show_sandbox_status


@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)

    # 配置日志
    setup_logging(project_dir)
    logger = logging.getLogger(__name__)
    logger.info(f"程序启动，项目目录: {project_dir}", extra={'tag': 'APP_START'})

    # 加载用户配置
    user_profile = get_user_profile(project_dir)
    current_task_mode = user_profile.task_mode  # 从配置读取任务模式

    # 实例化任务管理器
    task_manager = TaskManager(project_directory=project_dir, history_file="task_history.json")

    # 检测是否有未完成的会话
    pending_session = task_manager.get_last_session()
    has_pending = pending_session and pending_session['status'] in ('run ', 'fail')

    # 当前选中选项
    current_selection = '1'

    while True:
        if current_selection == '1':
            # 任务模式
            _show_main_menu(has_pending, pending_session, project_dir, current_task_mode)

            user_input = input("> ").strip()

            if not user_input:
                continue

            if user_input.lower() == 'q':
                print("\n程序已退出")
                return

            # 处理选项切换
            if has_pending:
                # 有未完成会话时的选项映射
                if user_input == '2':
                    current_selection = '2'
                    continue
                elif user_input == '3':
                    current_selection = '3'
                    continue
                elif user_input == '4':
                    # 恢复未完成会话
                    _run_task(
                        project_dir,
                        logger,
                        pending_session['original_task'],
                        pending_session['session_id'],
                        True,
                        is_new=False
                    )
                    return
                    # 执行完成后清除未完成状态
                    has_pending = False
                    pending_session = None
                    continue
                elif user_input == '5':
                    # 放弃未完成会话
                    from utils.session_persistence import SessionPersistence
                    sp = SessionPersistence(project_dir)
                    sp.mark_failed(pending_session['session_id'])
                    print(f"\n已放弃会话 {pending_session['session_id']}")
                    has_pending = False
                    pending_session = None
                    continue
                elif user_input == '1':
                    # 模式切换
                    new_mode = 'long' if current_task_mode == 'short' else 'short'
                    print(f"\n按回车切换到【{'长任务' if new_mode == 'long' else '短任务'}模式】，或输入 q 返回：")
                    confirm = input("> ").strip().lower()
                    if confirm == 'q':
                        continue
                    current_task_mode = new_mode
                    user_profile.task_mode = new_mode  # 保存到配置
                    mode_name = '长任务' if current_task_mode == 'long' else '短任务'
                    print(f"\n✅ 已切换到{mode_name}模式")
                    continue
                else:
                    # 普通任务文本
                    pass
            else:
                # 无未完成会话时的选项映射
                if user_input == '2':
                    current_selection = '2'
                    continue
                elif user_input == '3':
                    current_selection = '3'
                    continue
                elif user_input == '1':
                    # 模式切换
                    new_mode = 'long' if current_task_mode == 'short' else 'short'
                    print(f"\n按回车切换到【{'长任务' if new_mode == 'long' else '短任务'}模式】，或输入 q 返回：")
                    confirm = input("> ").strip().lower()
                    if confirm == 'q':
                        continue
                    current_task_mode = new_mode
                    user_profile.task_mode = new_mode  # 保存到配置
                    mode_name = '长任务' if current_task_mode == 'long' else '短任务'
                    print(f"\n✅ 已切换到{mode_name}模式")
                    continue

            # 处理普通任务文本
            user_query = user_input
            is_from_history = False
            session_id = task_manager.save_task(user_query, task_mode=exec_task_mode)

            # 启动任务（传入新创建的 session_id 和 task_mode）
            _run_task(project_dir, logger, user_query, session_id, is_from_history, is_new=True, task_mode=exec_task_mode)

            return

        elif current_selection == '2':
            # 配置沙盒
            print("\n进入沙盒配置...")
            quick_setup_sandbox(project_dir)
            current_selection = '1'

        elif current_selection == '3':
            # 查看历史任务
            result = _handle_history_selection(task_manager, current_task_mode)
            if result:
                user_query, should_resume, exec_task_mode = result
                is_from_history = True

                if should_resume:
                    # 用户选择继续执行（恢复）
                    last_session = task_manager.get_last_session()
                    if last_session and last_session['original_task'] == user_query:
                        resume_session_id = last_session['session_id']
                        print(f"\n恢复会话 {resume_session_id}...")
                        _run_task(project_dir, logger, user_query, resume_session_id, is_from_history, is_new=False, task_mode=exec_task_mode)
                    else:
                        # 找不到可恢复的会话，新建执行
                        session_id = task_manager.save_task(user_query, task_mode=exec_task_mode)
                        _run_task(project_dir, logger, user_query, session_id, is_from_history, is_new=True, task_mode=exec_task_mode)
                else:
                    # 用户选择重新执行（新建会话）
                    session_id = task_manager.save_task(user_query, task_mode=exec_task_mode)
                    _run_task(project_dir, logger, user_query, session_id, is_from_history, is_new=True, task_mode=exec_task_mode)

                return
            current_selection = '1'


def _show_main_menu(has_pending, pending_session, project_dir, task_mode='short'):
    """显示主菜单"""
    print("\n" + "=" * 60)

    # 获取沙盒配置信息
    sandbox_info = _get_sandbox_info(project_dir)

    # 模式显示文本
    mode_display = {'short': '短任务模式', 'long': '长任务模式'}

    if has_pending and pending_session:
        print("🔔 检测到未完成的会话")
        print("=" * 60)
        print(f"会话ID: {pending_session['session_id']} | 状态: {pending_session['status']}")
        # 截取任务描述，避免过长
        task_preview = pending_session['original_task']
        if len(task_preview) > 100:
            task_preview = task_preview[:97] + "..."
        print(f"任务: {task_preview}")
        print("-" * 60)
        print("操作选项（输入数字选择功能，q 退出，直接输入文本后回车执行任务）：")
        print(f"  [1] 切换任务模式 （当前：{mode_display[task_mode]}）")
        print(f"  [2] 🔒 配置沙盒安全策略 {sandbox_info}")
        print("  [3] 📋 查看历史任务")
        print("  [4] 🔄 恢复此会话并继续执行")
        print("  [5] ❌ 放弃此会话")
        print("  [q] 退出")
    else:
        print("操作选项（输入数字选择功能，q 退出，直接输入文本后回车执行任务）：")
        print(f"  [1] 切换任务模式 （当前：{mode_display[task_mode]}）")
        print(f"  [2] 🔒 配置沙盒安全策略 {sandbox_info}")
        print("  [3] 📋 查看历史任务")
        print("  [q] 退出")

    print("-" * 60)


def _get_sandbox_info(project_dir):
    """获取沙盒配置信息字符串"""
    try:
        import yaml
        policy_file = os.path.join(project_dir, "config", "sandbox_policy.yaml")

        if not os.path.exists(policy_file):
            return ""

        with open(policy_file, 'r', encoding='utf-8') as f:
            policy = yaml.safe_load(f) or {}

        mode = policy.get('mode', 'normal')
        mode_desc = {
            'strict': '严格模式',
            'normal': '标准模式',
            'permissive': '宽松模式'
        }.get(mode, mode)

        # 从 command_categories 计算允许的命令数量
        categories = policy.get('command_categories', {})
        total_cmds = 0
        for cat_config in categories.values():
            total_cmds += len(cat_config.get('strict', []))
            total_cmds += len(cat_config.get('normal', []))
            total_cmds += len(cat_config.get('permissive', []))

        allowed_dirs = policy.get('allowed_directories', [])
        dirs_count = len(allowed_dirs)

        return f"({mode_desc} | 允许命令: {total_cmds}条 | 允许路径: {dirs_count}个)"
    except Exception:
        return ""


def _handle_history_selection(task_manager, global_task_mode: str = 'short') -> Optional[Tuple[str, bool, str]]:
    """处理历史任务选择

    Args:
        task_manager: 任务管理器实例
        global_task_mode: 当前全局任务模式 ('short' 或 'long')

    Returns:
        Tuple[任务内容, 是否恢复, 执行用的模式] 或 None
    """
    from datetime import datetime

    total_count = task_manager.persistence.get_total_session_count()
    if total_count == 0:
        print("暂无历史任务")
        return None

    page_size = 20
    offset = max(0, total_count - page_size)

    while True:
        tasks = task_manager.persistence.list_sessions(limit=page_size, offset=offset)

        if tasks:
            start_id = tasks[0].get("session_id", "N/A") if tasks else "N/A"
            end_id = tasks[-1].get("session_id", "N/A") if tasks else "N/A"

            print("\n" + "=" * 80)
            print(f"历史任务列表 (共{total_count}个，显示ID {start_id}-{end_id})")
            print("=" * 80)

            for task_record in tasks:
                task_id = task_record.get("session_id", "N/A")
                task_content = task_record.get("original_task", "")
                status = task_record.get("status", "unknown")
                task_mode = task_record.get("task_mode", "short")
                created_at = task_record.get("created_at", "")

                time_str = "未知时间"
                if created_at:
                    try:
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        time_str = dt.strftime("%m-%d %H:%M")
                    except:
                        pass

                preview = task_content[:50] + "..." if len(task_content) > 50 else task_content
                status_word = status[:4] if len(status) >= 4 else status.ljust(4)
                mode_indicator = "L" if task_mode == "long" else "S"

                print(f"[{task_id:3d}] [{status_word}] [{mode_indicator}] [{time_str}] {preview}")

            print("=" * 80)
        else:
            print("暂无历史任务")
            return None

        print("\n" + "-" * 60)
        print("操作:")
        print("  [编号] 输入编号查看任务详情")
        if offset > 0:
            print("  [p] 向上翻页（查看更早的）")
        if offset + page_size < total_count:
            print("  [n] 向下翻页（查看更新的）")
        print("  [q] 返回")
        print("-" * 60)

        choice = input("> ").strip()

        if not choice:
            continue

        if choice.lower() == 'q':
            return None

        if choice.lower() == 'p' and offset > 0:
            offset = max(0, offset - page_size)
            continue

        if choice.lower() == 'n' and offset + page_size < total_count:
            offset = min(total_count - page_size, offset + page_size)
            continue

        if choice.isdigit():
            task_id = int(choice)
            task_record = task_manager.get_task_by_id(task_id)

            if not task_record:
                print(f"任务 ID {task_id} 不存在")
                continue

            task_content = task_record.get("original_task", "")
            status = task_record.get("status", "unknown")
            history_task_mode = task_record.get("task_mode", "short")  # 任务自己的模式
            mode_display = {'short': '短任务', 'long': '长任务'}

            print("\n" + "=" * 60)
            print(f"历史任务 {task_id}:")
            print("=" * 60)
            print(f"状态: {status}")
            print(f"记录模式: {mode_display[history_task_mode]}")
            print(task_content)
            print("=" * 60)

            # 根据状态显示不同选项
            if status in ('fail', 'run '):
                # 失败/中断的任务：可以继续或重新执行
                # 继续执行用历史模式，重新执行用全局模式
                continue_mode = history_task_mode
                new_mode = global_task_mode

                print(f"\n该任务之前执行失败/中断，选择操作:")
                print(f"  [c] 继续执行（恢复）- 使用【{mode_display[continue_mode]}】模式")
                if continue_mode != global_task_mode:
                    print(f"      （与当前全局设置 {mode_display[global_task_mode]} 不同）")
                print(f"  [n] 重新执行（新建）- 使用当前【{mode_display[new_mode]}】模式")
                print("  [q] 返回")
                print("-" * 60)

                choice = input("> ").strip().lower()
                if choice == 'q':
                    continue
                elif choice == 'c':
                    # 继续执行 - 使用历史任务模式，但支持临时切换
                    exec_mode = continue_mode
                    if exec_mode != global_task_mode:
                        print(f"\n将使用任务原记录的【{mode_display[exec_mode]}】模式执行")

                    # 询问是否临时切换
                    print(f"\n按回车确认，或输入临时切换:")
                    print(f"  [s] 短任务模式")
                    print(f"  [l] 长任务模式")
                    print(f"  [q] 返回")
                    mode_choice = input("> ").strip().lower()

                    if mode_choice == 'q':
                        continue
                    elif mode_choice == 's':
                        exec_mode = 'short'
                        print(f"✓ 临时切换为短任务模式")
                    elif mode_choice == 'l':
                        exec_mode = 'long'
                        print(f"✓ 临时切换为长任务模式")
                    elif mode_choice != '':
                        print("无效选择，使用默认模式")

                    task_manager.current_task_id = task_id
                    return task_content, True, exec_mode  # (内容, 恢复, 模式)
                elif choice == 'n':
                    # 重新执行 - 使用全局模式，但支持临时切换
                    exec_mode = new_mode
                    print(f"\n按回车以当前【{mode_display[exec_mode]}】模式执行，或输入临时切换:")
                    print(f"  [s] 短任务模式")
                    print(f"  [l] 长任务模式")
                    print(f"  [q] 返回")
                    mode_choice = input("> ").strip().lower()

                    if mode_choice == 'q':
                        continue
                    elif mode_choice == 's':
                        exec_mode = 'short'
                        print(f"✓ 临时切换为短任务模式")
                    elif mode_choice == 'l':
                        exec_mode = 'long'
                        print(f"✓ 临时切换为长任务模式")
                    elif mode_choice != '':
                        print("无效选择，使用默认模式")

                    task_manager.current_task_id = task_id
                    return task_content, False, exec_mode  # (内容, 新建, 模式)
                else:
                    print("无效选择，返回任务列表")
                    continue
            else:
                # 已完成的任务：重新执行，使用全局模式
                exec_mode = global_task_mode

                print(f"\n按回车以当前【{mode_display[exec_mode]}】模式执行，或输入临时切换:")
                print(f"  [s] 短任务模式")
                print(f"  [l] 长任务模式")
                print(f"  [q] 返回")

                mode_choice = input("> ").strip().lower()

                if mode_choice == 'q':
                    continue
                elif mode_choice == 's':
                    exec_mode = 'short'
                    print(f"✓ 临时切换为短任务模式")
                elif mode_choice == 'l':
                    exec_mode = 'long'
                    print(f"✓ 临时切换为长任务模式")
                elif mode_choice != '':
                    print("无效选择，使用当前全局模式")

                task_manager.current_task_id = task_id
                return task_content, False, exec_mode  # (内容, 新建, 模式)

        print("无效输入，请重试")
def _check_resume_session(project_dir, task_manager):
    """检查是否有未完成的会话，询问用户是否恢复"""
    last_session = task_manager.get_last_session()
    resume_session_id = None

    if last_session and last_session['status'] in ('run ', 'fail'):
        print("\n" + "!" * 60)
        print("检测到未完成的会话")
        print("!" * 60)
        print(f"会话ID: {last_session['session_id']}")
        print(f"任务: {last_session['original_task']}")
        print("-" * 60)
        print("选择操作:")
        print("  [r] 恢复上次会话")
        print("  [n] 放弃并新建任务")
        print("!" * 60)

        choice = input("\n> ").strip().lower()
        if choice == 'r':
            resume_session_id = last_session['session_id']
            print(f"\n恢复会话 {resume_session_id}...")
        else:
            from utils.session_persistence import SessionPersistence
            sp = SessionPersistence(project_dir)
            sp.mark_failed(last_session['session_id'])
            print("已放弃上次会话\n")

    return resume_session_id


def _run_task(project_dir, logger, user_query, session_id, is_from_history, is_new=False, task_mode='short'):
    """运行任务"""
    mode_name = '长任务' if task_mode == 'long' else '短任务'
    logger.info(f"开始处理{mode_name} (来源: {'历史记录' if is_from_history else '新输入'})",
                extra={'tag': 'TASK_START'})
    logger.info(f"直接启动 ReAct Agent 处理任务: {user_query}...",
                extra={'tag': 'DIRECT_REACT'})

    print("\n" + "=" * 60)
    print(f"🚀 启动 ReAct Agent ({mode_name}模式)")
    print("=" * 60)
    print(f"任务: {user_query}")
    print("-" * 60)

    try:
        react_agent = ReActAgent(project_directory=project_dir, task_mode=task_mode)
        final_report = react_agent.run(user_query, session_id=session_id, is_new=is_new)
        logger.info("ReAct Agent 执行完成", extra={'tag': 'REACT_END'})

        print("\n" + "=" * 60)
        print("✅ 任务执行完成!")
        print("=" * 60)
        print(final_report)
        print("=" * 60)

    except Exception as e:
        logger.error(f"ReAct Agent 执行失败: {str(e)}", extra={'tag': 'REACT_ERROR'})
        print(f"\n❌ 任务执行失败: {str(e)}")


if __name__ == "__main__":
    main()
