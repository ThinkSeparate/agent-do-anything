# agent.py (简化版，与新的TaskManager配合)
import os
import logging
import click

from utils import setup_logging
from core import ReActAgent
from utils.task_manager import TaskManager  # 导入新的TaskManager

@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)

    # 配置日志
    setup_logging(project_dir)
    
    # 记录程序开始
    logging.info(f"程序启动，项目目录: {project_dir}", extra={'tag': 'APP_START'})

    # 实例化智能体和任务管理器
    agent = ReActAgent(project_directory=project_dir)
    task_manager = TaskManager(project_directory=project_dir, history_file="task_history.json")

    # 使用简化版任务管理器获取任务
    task_info = task_manager.get_task_input()
    
    if not task_info or not task_info[0]:
        logging.info("未获取到有效任务，程序退出", extra={'tag': 'APP_EXIT'})
        return
    
    task, is_from_history = task_info
    
    # 记录任务开始
    logging.info(f"开始执行任务 (来源: {'历史记录' if is_from_history else '新输入'})", 
                 extra={'tag': 'TASK_START'})
    logging.info(f"任务内容: {task[:100]}...", extra={'tag': 'TASK_CONTENT'})
    
    try:
        # 执行任务
        final_answer = agent.run(task)
        
        # 记录任务完成
        logging.info("任务执行完成", extra={'tag': 'TASK_END'})
        
        # 输出结果
        print("\n" + "="*60)
        print("✅ 任务完成!")
        print("="*60)
        print(final_answer)
        print("="*60)
        
    except Exception as e:
        logging.error(f"任务执行失败: {str(e)}", extra={'tag': 'TASK_ERROR'})
        print(f"\n❌ 任务执行失败: {str(e)}")

if __name__ == "__main__":
    main()