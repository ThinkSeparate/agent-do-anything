# agent.py (位于项目根目录)
import os
import logging
import click

# 关键修改：从新的包结构中导入所有需要的组件
from utils import setup_logging
from core import ReActAgent


@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)

    # 配置日志
    setup_logging(project_dir)
    
    # 记录程序开始
    logging.info(f"程序启动，项目目录: {project_dir}", extra={'tag': 'APP_START'})

    # 实例化智能体
    agent = ReActAgent(project_directory=project_dir)

    task = input("请输入任务：")

    logging.info("开始执行任务", extra={'tag': 'TASK_START'})
    final_answer = agent.run(task)
    logging.info("任务执行完成", extra={'tag': 'TASK_END'})
    logging.info(f"\n\n✅ 最终答案: {final_answer}", extra={'tag': 'FINAL_OUTPUT'})

if __name__ == "__main__":
    main()