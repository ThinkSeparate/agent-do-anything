# core/plan/agent.py
import logging
from langchain.messages import HumanMessage

from config.configuration import config
from tools import get_plan_tools
from core.common import agent_utils
from core.plan.prompts import plan_system_prompt_template
from core.plan.build_agent import build_plan_graph
from core.plan.state_define import PlanState


class PlanAgent:
    """
    规划与协调代理。
    负责任务分解、协调执行和动态重新规划。
    """

    def __init__(self, project_directory: str):
        self.logger = logging.getLogger(__name__)
        self.logger.info("PlanAgent 初始化开始", extra={'tag': 'PLAN_AGENT_INIT'})
        self.project_directory = project_directory

        # 1. 使用公共函数加载配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout']
        agent_utils.load_agent_config(required_keys)
        
        # 2. 准备模型配置
        model_keys = {
            'model_name': config.get('model.name'),
            'base_url': config.get('model.base_url'),
            'api_key': config.get('model.api_key'),
            'timeout': config.get('model.timeout'),
        }
        
        # 3. 使用公共函数创建模型（绑定工具）
        self.model_with_tools = agent_utils.create_agent_model(
            model_keys=model_keys,
            tools_getter=get_plan_tools
        )

        # 4. 使用公共函数渲染系统提示
        rendered_prompt = agent_utils.render_system_prompt(
            template=plan_system_prompt_template,
            project_directory=project_directory
        )

        # 5. 构建规划图
        self.graph = build_plan_graph(
            model_with_tools=self.model_with_tools,
            system_prompt=rendered_prompt,
            project_directory=project_directory
        )

        self.logger.info("PlanAgent 初始化完成", extra={'tag': 'PLAN_AGENT_INIT'})

    def run(self, task_description: str) -> str:
        """
        运行规划代理
        
        Args:
            task_description: 已澄清的任务描述
        
        Returns:
            最终的执行结果报告
        """
        self.logger.info(f"开始任务规划，任务: {task_description}", extra={'tag': 'PLAN_START'})

        # 初始化状态
        initial_state: PlanState = {
            "messages": [HumanMessage(content=task_description)],
            "original_task": task_description,
            "plan_tree": None,
            "completed_tasks": [],
            "pending_tasks": [],
            "current_phase": "planning",
            "execution_context": {},
            "consecutive_failures": 0,
            "max_failures": 3
        }

        try:
            # 执行规划图
            final_state = self.graph.invoke(initial_state)
            
            # 提取最终结果
            messages = final_state["messages"]
            
            # 查找最终报告
            for msg in reversed(messages):
                if msg.type == "tool" and "最终报告" in str(msg.content):
                    return msg.content
                elif msg.type == "ai" and "final_report" in str(msg.content).lower():
                    return msg.content
            
            # 如果没有找到报告，返回最后一条消息
            if messages:
                return str(messages[-1].content)
            
            return "规划执行完成，但未生成报告。"
            
        except Exception as e:
            self.logger.error(f"规划过程出错: {str(e)}", extra={'tag': 'PLAN_ERROR'})
            return f"规划过程发生错误: {str(e)}"