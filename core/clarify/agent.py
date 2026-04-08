# core/clarify/agent.py
import logging
from langchain.messages import HumanMessage

from config.configuration import config
from tools import get_clarify_tools
from core.common import agent_utils
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
            tools_getter=get_clarify_tools
        )

        # 4. 使用公共函数渲染系统提示
        rendered_prompt = agent_utils.render_system_prompt(
            template=clarify_system_prompt_template,
            project_directory=project_directory
        )

        # 5. 构建澄清图
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