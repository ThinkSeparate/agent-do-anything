# agent.py (修改后的主函数部分)
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
from core.react.agent import ReActAgent  # 原有的执行Agent
from core.clarify.agent import ClarifyAgent  # 新增加的需求澄清Agent
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
    task_info = task_manager.get_task_input()

    if not task_info or not task_info[0]:
        logger.info("未获取到有效任务，程序退出", extra={'tag': 'APP_EXIT'})
        return

    user_query, is_from_history = task_info
    logger.info(f"开始处理任务 (来源: {'历史记录' if is_from_history else '新输入'})",
                extra={'tag': 'TASK_START'})

    # ========== 第1步：需求澄清 ==========
    logger.info("启动需求澄清阶段...", extra={'tag': 'CLARIFY_PHASE'})
    
    clarify_agent = ClarifyAgent(project_directory=project_dir)
    clarify_result = clarify_agent.run(user_query)
    
    decision = clarify_result.get('decision', 'need_react')
    clarified_task = clarify_result.get('clarified_task', user_query)
    history = clarify_result.get('history', [])
    
    # ========== 第2步：根据澄清结果分流 ==========
    if decision == 'direct_answer':
        # 情况A：直接回答
        final_answer = clarify_result.get('final_answer', '')
        logger.info(f"需求澄清结论：直接回答。答案长度: {len(final_answer)}", 
                   extra={'tag': 'DECISION_DIRECT'})
        
        # 输出结果
        print("\n" + "="*60)
        print("💬 任务完成 (直接回答)")
        print("="*60)
        print(final_answer)
        print("="*60)
        
    elif decision == 'need_react':
        # 情况B：需要复杂操作，启动ReActAgent
        logger.info(f"需求澄清结论：复杂操作需求，启动ReActAgent。任务: {clarified_task}...",
                   extra={'tag': 'DECISION_REACT'})
        
        print("\n" + "="*60)
        print("🛠️  任务类型：复杂操作 (启动执行Agent...)")
        print("="*60)
        print(f"任务描述: {clarified_task}")
        print("="*60)
        
        # 实例化并运行ReActAgent，传入已澄清的任务描述
        react_agent = ReActAgent(project_directory=project_dir)
        try:
            final_output = react_agent.run(clarified_task)
            logger.info("ReActAgent 执行完成", extra={'tag': 'REACT_END'})
            
            print("\n" + "="*60)
            print("✅ 任务执行完成!")
            print("="*60)
            print(final_output)
            print("="*60)
            
        except Exception as e:
            logger.error(f"ReActAgent 执行失败: {str(e)}", extra={'tag': 'REACT_ERROR'})
            print(f"\n❌ 任务执行失败: {str(e)}")


if __name__ == "__main__":
    main()