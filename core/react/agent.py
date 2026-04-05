# core/react/agent.py
import os
import platform
import logging
from string import Template

from langchain.messages import HumanMessage

from config.configuration import config
from tools import all_tools, configure_agent_output_root
from core.common.model_define import create_chat_model, bind_tools_to_model
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

        # 0. 加载并验证必需配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout', 'agent.output_root']
        config.load(required_keys=required_keys)

        # 从配置中读取路径
        self.agent_output_root = self.get_output_root(config.get('agent.output_root'))
        configure_agent_output_root(lambda: self.agent_output_root)
        self.logger.info(f"已从配置加载安全写入目录: {self.agent_output_root}", extra={'tag': 'AGENT_INIT'})

        # 1. 初始化 ChatOpenAI 模型
        self.model = create_chat_model(
            model_name=config.get('model.name'),
            base_url=config.get('model.base_url'),
            api_key=config.get('model.api_key'),
            timeout=config.get('model.timeout'),
        )

        # 2. 绑定工具到模型
        self.model_with_tools = bind_tools_to_model(self.model, all_tools)

        # 3. 渲染系统提示
        rendered_prompt = self.render_system_prompt(system_prompt_template)

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

    def render_system_prompt(self, template: str) -> str:
        """渲染系统提示模板，替换变量。"""
        self.logger.debug("开始渲染系统提示模板", extra={'tag': 'PROMPT_RENDER'})

        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )

        result = Template(template).substitute(
            operating_system=self.get_operating_system_name(),
            file_list=file_list,
            agent_output=self.agent_output_root
        )

        self.logger.debug(f"系统提示渲染完成，长度: {len(result)} 字符",
                          extra={'tag': 'PROMPT_RENDER'})
        return result

    def get_output_root(self, output_root):
        output_root_config = config.get('agent.output_root')
        if os.path.isabs(output_root_config):
            agent_output_root = output_root_config
        else:
            agent_output_root = os.path.join(self.project_directory, output_root_config)
        return os.path.abspath(agent_output_root)

    @staticmethod
    def get_env(env_key) -> str:
        """封装环境变量获取。"""
        return os.environ.get(env_key, "")

    def get_operating_system_name(self):
        """获取操作系统名称。"""
        os_map = {
            "Darwin": "macOS",
            "Windows": "Windows",
            "Linux": "Linux"
        }

        system_name = platform.system()
        os_name = os_map.get(system_name, "Unknown")
        self.logger.debug(f"检测到操作系统: {system_name} -> {os_name}",
                          extra={'tag': 'OS_DETECT'})
        return os_name
