# core/react/agent.py
import os
import logging
from langchain.messages import HumanMessage

from config.configuration import config
from tools import get_react_tools, configure_agent_output_root
from core.common import agent_utils
from core.react.prompts import system_prompt_template
from core.react.build_agent import build_react_graph


class ReActAgent:
    """
    主代理类，负责初始化所有组件并协调工作。
    这是对外的唯一接口，保持与原有调用方式兼容。
    """

    def __init__(self, project_directory: str):
        self.logger = logging.getLogger(__name__)
        self.logger.info("ReActAgent 初始化开始", extra={'tag': 'AGENT_INIT'})
        self.project_directory = project_directory

        # 0. 使用公共函数加载配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout', 'agent.output_root']
        agent_utils.load_agent_config(required_keys)

        # 从配置中读取路径
        self.agent_output_root = agent_utils.get_agent_output_root(self.project_directory, config.get('agent.output_root'))
        configure_agent_output_root(lambda: self.agent_output_root)
        self.logger.info(f"已从配置加载安全写入目录: {self.agent_output_root}", extra={'tag': 'AGENT_INIT'})

        # 1. 准备模型配置
        model_keys = {
            'model_name': config.get('model.name'),
            'base_url': config.get('model.base_url'),
            'api_key': config.get('model.api_key'),
            'timeout': config.get('model.timeout'),
        }
        
        # 2. 使用公共函数创建模型（绑定工具）
        self.model_with_tools = agent_utils.create_agent_model(
            model_keys=model_keys,
            tools_getter=get_react_tools
        )

        # 3. 使用公共函数渲染系统提示
        context_limit = config.get('model.context_limit', 128000)
        compress_threshold = config.get('model.context_compress_threshold', 100000)

        rendered_prompt = agent_utils.render_system_prompt(
            template=system_prompt_template,
            project_directory=project_directory,
            additional_vars={
                'agent_output': self.agent_output_root,
                'context_limit': context_limit,
                'compress_threshold': compress_threshold
            }
        )

        # 4. 构建 LangGraph 图
        self.graph = build_react_graph(
            model_with_tools=self.model_with_tools,
            system_prompt=rendered_prompt,
        )

        self.logger.info("ReActAgent 初始化完成", extra={'tag': 'AGENT_INIT'})

    def run(self, user_input: str) -> str:
        """
        运行代理处理用户输入。

        Args:
            user_input: 用户输入的问题或指令

        Returns:
            模型的最终回答文本
        """
        self.logger.info(f"用户输入: {user_input}", extra={'tag': 'USER_INPUT'})

        try:
            initial_state = {
                "messages": [HumanMessage(content=user_input)],
                "consecutive_failures": 0,
            }

            final_state = self.graph.invoke(initial_state)

            messages = final_state["messages"]
            last_message = messages[-1]
            final_answer = last_message.content

            self.logger.info("任务执行完成", extra={'tag': 'TASK_END'})
            return final_answer

        except Exception as e:
            self.logger.critical(f"任务执行过程中发生未捕获的异常: {e}", exc_info=True,
                                 extra={'tag': 'TASK_CRASH'})
            return f"任务执行过程发生意外错误，已终止。错误类型：{type(e).__name__}"
