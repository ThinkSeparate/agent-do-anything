# core/react/agent.py
import os
import logging
from langchain.messages import HumanMessage
from langchain_core.messages import messages_from_dict

from config.configuration import config
from tools import get_react_tools, configure_agent_output_root
from core.common import agent_utils
from core.react.prompts import system_prompt_template
from core.react.build_agent import build_react_graph
from utils.session_persistence import SessionPersistence


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

        self.rendered_prompt = agent_utils.render_system_prompt(
            template=system_prompt_template,
            project_directory=project_directory,
            additional_vars={
                'agent_output': self.agent_output_root,
                'context_limit': context_limit,
                'compress_threshold': compress_threshold
            }
        )

        self.logger.info("ReActAgent 初始化完成", extra={'tag': 'AGENT_INIT'})

    def run(self, user_input: str, resume_from_session_id: int = None) -> str:
        """
        运行代理处理用户输入。

        Args:
            user_input: 用户输入的问题或指令
            resume_from_session_id: 要恢复的历史会话ID（可选）

        Returns:
            模型的最终回答文本
        """
        persistence = SessionPersistence(self.project_directory)
        session_id = resume_from_session_id

        # 恢复模式
        if resume_from_session_id:
            self.logger.info(f"从会话 {resume_from_session_id} 恢复执行",
                           extra={'tag': 'RESUME_SESSION'})
            saved_state = persistence.load_state(resume_from_session_id)
            if saved_state:
                messages = messages_from_dict(saved_state["messages"])
                consecutive_failures = saved_state.get("consecutive_failures", 0)
                initial_state = {
                    "messages": messages,
                    "consecutive_failures": consecutive_failures,
                }
            else:
                self.logger.error(f"无法加载会话状态: {resume_from_session_id}")
                return f"错误：无法恢复会话 {resume_from_session_id}"
        else:
            # 新会话模式
            self.logger.info(f"用户输入: {user_input}", extra={'tag': 'USER_INPUT'})

            # 创建新会话记录
            session_id = persistence.create_session(user_input)
            self.logger.info(f"新会话创建: {session_id}", extra={'tag': 'SESSION_CREATED'})

            # 添加目录规范备注
            directory_note = f"""\n\n【备注】如需创建文件/目录，请优先使用 `{self.agent_output_root}` 目录，并遵守该目录下的使用规范 `directory_management_rules.md`。"""
            enhanced_input = user_input + directory_note

            initial_state = {
                "messages": [HumanMessage(content=enhanced_input)],
                "consecutive_failures": 0,
            }

        # 构建 LangGraph 图（传递 session_id 用于状态保存）
        self.graph = build_react_graph(
            model_with_tools=self.model_with_tools,
            system_prompt=self.rendered_prompt,
            session_id=session_id,
            project_directory=self.project_directory
        )

        try:
            final_state = self.graph.invoke(initial_state)

            messages = final_state["messages"]
            last_message = messages[-1]
            final_answer = last_message.content

            # 标记会话完成
            if session_id:
                persistence.mark_completed(session_id)

            self.logger.info("任务执行完成", extra={'tag': 'TASK_END'})
            return final_answer

        except Exception as e:
            self.logger.critical(f"任务执行过程中发生未捕获的异常: {e}", exc_info=True,
                                 extra={'tag': 'TASK_CRASH'})
            # 标记会话失败
            if session_id:
                persistence.mark_failed(session_id)
            return f"任务执行过程发生意外错误，已终止。错误类型：{type(e).__name__}"
