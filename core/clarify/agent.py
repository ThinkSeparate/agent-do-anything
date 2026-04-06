# core/clarify/agent.py
import os
import platform
import logging
from string import Template

from langchain.messages import HumanMessage

from config.configuration import config
from tools import all_tools_with_think  # 需要 ask_user, submit_final_answer
from core.common.model_define import create_chat_model, bind_tools_to_model
from core.clarify.prompts import clarify_system_prompt_template
from core.clarify.build_agent import build_clarify_graph


class ClarifyAgent:
    """
    需求澄清代理。
    负责与用户交互，澄清需求，并判断需求类型。
    """

    def __init__(self, project_directory: str):
        self.logger = logging.getLogger(__name__)
        self.logger.info("ClarifyAgent 初始化开始", extra={'tag': 'CLARIFY_AGENT_INIT'})

        self.project_directory = project_directory

        # 加载配置 (可以复用react agent的配置项)
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout']
        config.load(required_keys=required_keys)

        # 1. 初始化模型
        self.model = create_chat_model(
            model_name=config.get('model.name'),
            base_url=config.get('model.base_url'),
            api_key=config.get('model.api_key'),
            timeout=config.get('model.timeout'),
        )

        # 2. 绑定工具（只需要交互类工具）
        needed_tool_names = ['ask_user', 'submit_final_answer', 'transfer_to_react']
        needed_tools = [tool for tool in all_tools_with_think if tool.name in needed_tool_names]
        self.model_with_tools = bind_tools_to_model(self.model, needed_tools)

        # 3. 渲染系统提示
        rendered_prompt = self.render_system_prompt(clarify_system_prompt_template)

        # 4. 构建澄清图
        self.graph = build_clarify_graph(
            model_with_tools=self.model_with_tools,
            system_prompt=rendered_prompt,
        )

        self.logger.info("ClarifyAgent 初始化完成", extra={'tag': 'CLARIFY_AGENT_INIT'})

    def run(self, user_input: str) -> dict:
        """
        运行澄清代理。
        """
        self.logger.info(f"开始需求澄清，用户输入: {user_input}", extra={'tag': 'CLARIFY_START'})

        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "consecutive_failures": 0,
        }

        try:
            # 设置最大澄清轮数
            max_turns = 5
            current_turn = 0
            
            while current_turn < max_turns:
                current_turn += 1
                final_state = self.graph.invoke(initial_state)
                
                # --- 检查流程结束的条件（修改开始）---
                # 获取最终状态的所有消息
                messages = final_state["messages"]
                
                # 检查最后一条消息是否为工具执行后返回的结果
                if messages and hasattr(messages[-1], 'content'):
                    # 如果最后一条消息是工具执行结果，则根据之前AI调用的工具类型判断决策
                    ai_messages = [msg for msg in messages if msg.type == "ai"]
                    if ai_messages:
                        last_ai_message = ai_messages[-1]
                        if hasattr(last_ai_message, 'tool_calls') and last_ai_message.tool_calls:
                            tool_name = last_ai_message.tool_calls[0].get("name", "")
                            
                            if tool_name == "submit_final_answer":
                                # 决策：直接回答。最终答案从消息历史的最后一条（工具执行结果）中获取
                                final_answer_text = messages[-1].content
                                return {
                                    'decision': 'direct_answer',
                                    'final_answer': final_answer_text,  # 改为从消息内容获取
                                    'history': messages,
                                }
                                
                            elif tool_name == "transfer_to_react":
                                # 决策：转交任务。任务描述仍从工具参数中提取
                                tool_args = last_ai_message.tool_calls[0].get("args", {})
                                clarified_task = tool_args.get("clarified_task_description", "")
                                if not clarified_task:
                                    clarified_task = user_input
                                return {
                                    'decision': 'need_react',
                                    'clarified_task': clarified_task,
                                    'history': messages,
                                }
                # --- 修改结束 ---
                
                # 如果还没有结束，更新状态继续循环
                initial_state = final_state
                
            # 超过最大轮数，强制转交
            self.logger.warning(f"需求澄清达到最大轮数 ({max_turns})，强制转交", extra={'tag': 'CLARIFY_TIMEOUT'})
            return {
                'decision': 'need_react',
                'clarified_task': user_input,  # 使用原始输入
                'history': final_state["messages"],
            }
            
        except Exception as e:
            self.logger.error(f"需求澄清过程出错: {str(e)}", extra={'tag': 'CLARIFY_ERROR'})
            # 出错时也转交
            return {
                'decision': 'need_react',
                'clarified_task': user_input,
                'history': [],
            }
        
    def render_system_prompt(self, template: str) -> str:
        """渲染系统提示模板。"""
        import os
        from string import Template
        
        # 获取文件列表
        try:
            files = os.listdir(self.project_directory)
            # 只显示前10个文件
            if len(files) > 10:
                file_list = ", ".join(files[:10]) + f" 等 {len(files)} 个文件"
            else:
                file_list = ", ".join(files)
        except:
            file_list = "无法读取目录"
        
        # 操作系统信息
        os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
        system_name = platform.system()
        os_name = os_map.get(system_name, "Unknown")
        
        return Template(template).substitute(
            operating_system=os_name,
            working_directory=self.project_directory,
            file_list=file_list,
        )