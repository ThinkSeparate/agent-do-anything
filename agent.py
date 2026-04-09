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
import click

from utils import setup_logging
from core.react.agent import ReActAgent  # 直接导入 ReAct Agent
from utils.task_manager import TaskManager

@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)

    # 配置日志
    setup_logging(project_dir)
    logger = logging.getLogger(__name__)
    logger.info(f"程序启动，项目目录: {project_dir}", extra={'tag': 'APP_START'})

    # 实例化任务管理器
    task_manager = TaskManager(project_directory=project_dir, history_file="task_history.json")

    # 检测最近的会话是否未完成
    last_session = task_manager.get_last_session()
    if last_session and last_session['status'] == 'run ':
        print("\n" + "!"*60)
        print("检测到未完成的会话")
        print("!"*60)
        print(f"会话ID: {last_session['session_id']}")
        print(f"任务: {last_session['original_task']}")
        print("-"*60)
        print("选择操作:")
        print("  [r] 恢复上次会话")
        print("  [n] 放弃并新建任务")
        print("!"*60)

        choice = input("\n> ").strip().lower()
        if choice == 'r':
            # 恢复模式
            user_query = last_session['original_task']
            is_from_history = True
            resume_session_id = last_session['session_id']
            print(f"\n恢复会话 {resume_session_id}...")
        else:
            # 放弃，标记为失败
            from utils.session_persistence import SessionPersistence
            sp = SessionPersistence(project_dir)
            sp.mark_failed(last_session['session_id'])
            print("已放弃上次会话\n")
            # 继续正常流程
            task_info = task_manager.get_task_input()
            if not task_info or not task_info[0]:
                return
            user_query, is_from_history = task_info
            resume_session_id = None
    else:
        # 正常流程
        task_info = task_manager.get_task_input()
        if not task_info or not task_info[0]:
            logger.info("未获取到有效任务，程序退出", extra={'tag': 'APP_EXIT'})
            return
        user_query, is_from_history = task_info
        resume_session_id = None

    # 如果是历史任务，检查状态
    if is_from_history and task_manager.current_task_id:
        session = task_manager.get_task_by_id(task_manager.current_task_id)
        if session:
            if session['status'] == 'done':
                # 已完成，作为新任务执行（复制描述，创建新session）
                print("\n该任务已完成，将作为新任务执行...")
                resume_session_id = None
                # 不修改 user_query
            elif session['status'] in ['run ', 'fail']:
                # 未完成，询问用户
                print("\n" + "-"*60)
                print(f"任务 {task_manager.current_task_id} 状态: {session['status']}")
                print("-"*60)
                print("选择操作:")
                print("  [c] 继续执行（从断点恢复）")
                print("  [r] 重新开始（创建新会话）")
                print("-"*60)

                choice = input("> ").strip().lower()
                if choice == 'c':
                    resume_session_id = task_manager.current_task_id
                else:
                    # 作为新任务执行
                    resume_session_id = None
                    # 可选：标记原会话为失败
                    task_manager.persistence.mark_failed(task_manager.current_task_id)

    logger.info(f"开始处理任务 (来源: {'历史记录' if is_from_history else '新输入'})",
                extra={'tag': 'TASK_START'})

    # 直接启动 ReAct Agent（跳过需求澄清阶段）
    logger.info(f"直接启动 ReAct Agent 处理任务: {user_query}...",
               extra={'tag': 'DIRECT_REACT'})
    
    print("\n" + "="*60)
    print("🚀 直接启动 ReAct Agent 处理任务")
    print("="*60)
    print(f"任务描述: {user_query}")
    
    # 打印工作流信息
    print("\n" + "-"*60)
    print("🔄 简化工作流程")
    print("-"*60)
    print("1. 任务管理器 → ReAct Agent: ✅ 直接传递任务")
    print("2. 跳过 Clarify Agent: ✅ 无需求澄清阶段")
    print("3. 跳过 Plan Agent: ✅ 无规划阶段")
    print("-"*60)
    print("="*60)
    
    # 直接实例化并运行 ReAct Agent
    try:
        react_agent = ReActAgent(project_directory=project_dir)
        final_report = react_agent.run(user_query, resume_from_session_id=resume_session_id)
        logger.info("ReAct Agent 执行完成", extra={'tag': 'REACT_END'})
        
        print("\n" + "="*60)
        print("✅ 任务执行完成!")
        print("="*60)
        print(final_report)
        print("="*60)
        
    except Exception as e:
        logger.error(f"ReAct Agent 执行失败: {str(e)}", extra={'tag': 'REACT_ERROR'})
        print(f"\n❌ 任务执行失败: {str(e)}")

if __name__ == "__main__":
    main()