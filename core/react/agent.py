# core/react/agent.py
import os
import logging
from langchain.messages import HumanMessage, ToolMessage, AIMessage, RemoveMessage
from langchain_core.messages import messages_from_dict
from config.configuration import config




from tools import get_react_tools, configure_agent_output_root
from utils.token_utils import (
    calculate_tools_token_count, set_tools_token_count,
    set_model_name, set_tools_list
)
from core.common import agent_utils
from core.common.message_validator import validate_and_repair, MessageValidationError
from core.react.prompts import system_prompt_template
from core.react.build_agent import build_react_graph
from utils.session_persistence import SessionPersistence


class ReActAgent:
    """
    主代理类，负责初始化所有组件并协调工作。
    这是对外的唯一接口，保持与原有调用方式兼容。
    """

    def __init__(self, project_directory: str, task_mode: str = 'short'):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"ReActAgent 初始化开始 (模式: {task_mode})", extra={'tag': 'AGENT_INIT'})
        self.project_directory = project_directory
        self.task_mode = task_mode

        # 0. 使用公共函数加载配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout', 'agent.output_root']
        agent_utils.load_agent_config(required_keys)

        # 从配置中读取路径
        self.agent_output_root = agent_utils.get_agent_output_root(config.get('agent.output_root'), self.project_directory)
        configure_agent_output_root(lambda: self.agent_output_root)
        self.logger.info(f"已从配置加载safe写入目录: {self.agent_output_root}", extra={'tag': 'AGENT_INIT'})

        # 1. 准备模型配置
        model_keys = {
            'model_name': config.get('model.name'),
            'base_url': config.get('model.base_url'),
            'api_key': config.get('model.api_key'),
            'timeout': config.get('model.timeout'),
        }

        # 2. 设置模型名称（用于 token 计算）
        model_name = config.get('model.name', 'gpt-4')
        set_model_name(model_name)
        self.logger.info(f"使用模型: {model_name}", extra={'tag': 'AGENT_INIT'})

        # 3. 获取工具列表并计算工具 token 数量
        react_tools = get_react_tools(task_mode=task_mode)
        tools_token_count = calculate_tools_token_count(react_tools)
        set_tools_token_count(tools_token_count)
        set_tools_list(react_tools)  # 存储工具列表供 API 构造使用
        self.logger.info(f"工具定义占用 token: {tools_token_count}", extra={'tag': 'AGENT_INIT'})

        # 3. 使用公共函数创建模型（绑定工具）
        self.model_with_tools = agent_utils.create_agent_model(
            model_keys=model_keys,
            tools_getter=lambda: react_tools
        )

        # 3. 使用公共函数渲染系统提示
        context_limit = config.get('model.context_limit', 128000)
        compress_threshold = config.get('model.context_compress_threshold', 100000)

        # 根据模式选择结束工具名称和描述
        if task_mode == 'long':
            task_end_tool = 'submit_sub_task'
            task_end_description = '''    - **当你完成Current子任务时，调用 `${task_end_tool}` 工具提交完成内容。** 调用此工具后，系统将记录你的完成内容并等待用户的下一步输入，任务不会结束，而是进入下一个迭代周期。'''
            task_end_rule = '''**只有 `${task_end_tool}` 工具能正式提交子任务并等待用户输入。** 不要在思考中直接写出答案，也不要用其他工具来返回答案。长任务模式下，你将多次与用户交互直到用户输入 "done" 结束任务。'''
        else:
            task_end_tool = 'submit_final_answer'
            task_end_description = '''    - **如果你确信已收集到所有必要信息，可以回答用户最初的问题，则调用 `${task_end_tool}` 工具来交付最终答案。** 调用此工具意味着任务结束。'''
            task_end_rule = '''**只有 `${task_end_tool}` 工具能正式结束任务。** 不要在思考中直接写出答案，也不要用其他工具来返回答案。'''

        from core.react.prompts import system_prompt_template

        self.rendered_prompt = agent_utils.render_system_prompt(
            template=system_prompt_template,
            project_directory=project_directory,
            additional_vars={
                'agent_output': self.agent_output_root,
                'context_limit': context_limit,
                'compress_threshold': compress_threshold,
                'task_end_tool': task_end_tool,
                'task_end_description': task_end_description,
                'task_end_rule': task_end_rule
            }
        )

        self.logger.info("ReActAgent 初始化完成", extra={'tag': 'AGENT_INIT'})

    def run(self, user_input: str, session_id: int = None, is_new: bool = True) -> str:
        """
        运行代理Processed用户输入。

        Args:
            user_input: 用户输入的问题或指令
            session_id: 会话ID（外层已创建）
            is_new: 是否是新会话（False表示恢复）

        Returns:
            模型的最终回答文本
        """
        persistence = SessionPersistence(self.project_directory)

        # 恢复模式
        if not is_new and session_id:
            self.logger.info(f"从会话 {session_id} 恢复执行",
                           extra={'tag': 'RESUME_SESSION'})
            saved_state = persistence.load_state(session_id)
            if saved_state:
                messages = messages_from_dict(saved_state["messages"])
                # 【关键修复】过滤掉 RemoveMessage，避免重复删除已不存在的消息
                from langchain.messages import RemoveMessage
                original_count = len(messages)
                messages = [m for m in messages if not isinstance(m, RemoveMessage)]
                filtered_count = original_count - len(messages)
                if filtered_count > 0:
                    self.logger.info(f"会话恢复: 过滤掉 {filtered_count} 条 RemoveMessage",
                                   extra={'tag': 'RESUME_FILTER'})

                # 【新增】消息验证和修复（交互模式）
                # 自动修复尾部，如果中间有问题会询问用户
                try:
                    success, messages = validate_and_repair(
                        messages, self.logger
                    )
                except MessageValidationError as e:
                    self.logger.error(f"会话恢复: 消息验证失败，任务不可用: {e}", extra={'tag': 'RESUME_FAILED'})
                    persistence.mark_corrupted(session_id)
                    return None
                # 验证通过（自动修复或用户确认修复）
                self.logger.info("会话恢复: 消息验证通过", extra={'tag': 'RESUME_OK'})

                consecutive_failures = saved_state.get("consecutive_failures", 0)
                initial_state = {
                    "messages": messages,
                    "consecutive_failures": consecutive_failures,
                }
            else:
                self.logger.error(f"无法加载会话状态: {session_id}")
                return f"错误：无法恢复会话 {session_id}"
        else:
            # 新会话模式（session_id 已由外层创建）
            if not session_id:
                self.logger.error("新会话模式需要提供 session_id", extra={'tag': 'SESSION_ERROR'})
                return "错误：内部错误，未提供会话ID"

            self.logger.info(f"用户输入: {user_input}", extra={'tag': 'USER_INPUT'})
            self.logger.info(f"使用会话: {session_id}", extra={'tag': 'SESSION_USING'})

            # 添加目录规范备注
            # directory_note = f"""\n\n【备注】如需创建文件/目录，请优先使用 `{self.agent_output_root}` 目录，并遵守该目录下的使用规范 `directory_management_rules.md`。"""
            # enhanced_input = user_input + directory_note

            initial_state = {
                "messages": [HumanMessage(content=user_input)],
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
            # 长任务模式循环
            if self.task_mode == 'long':
                return self._run_long_task(initial_state, persistence, session_id)
            else:
                # 短任务模式：单次执行
                final_state = self.graph.invoke(initial_state)

                messages = final_state["messages"]
                last_message = messages[-1]
                final_answer = last_message.content

                # 标记会话完成
                if session_id:
                    persistence.mark_completed(session_id)

                self.logger.info("任务执行完成", extra={'tag': 'TASK_END'})
                return final_answer

        except (KeyboardInterrupt, SystemExit):
            # 用户中断或系统退出，不标记状态，保持run以便恢复
            self.logger.warning("任务被用户中断或系统退出，会话保持运行状态",
                               extra={'tag': 'TASK_INTERRUPTED'})
            raise  # 重新抛出，让上层Processed
        except MessageValidationError as e:
            # 消息验证失败且用户拒绝修复，标记会话为 corrupted
            self.logger.error(f"任务终止: {e}", extra={'tag': 'TASK_VALIDATION_FAILED'})
            if session_id:
                persistence.mark_corrupted(session_id)
            return f"任务终止: 消息上下文损坏且无法修复。{e}"
        except Exception as e:
            self.logger.critical(f"任务执行过程中发生未捕获的异常: {e}", exc_info=True,
                                 extra={'tag': 'TASK_CRASH'})
            # 标记会话失败
            if session_id:
                persistence.mark_failed(session_id)
            return f"任务执行过程发生意外错误，已终止。错误类型：{type(e).__name__}"

    def _run_long_task(self, initial_state, persistence, session_id):
        """长任务模式：支持多次迭代，直到用户输入 done"""
        from langchain.messages import HumanMessage, ToolMessage
        from langchain_core.messages import message_to_dict

        current_state = initial_state

        # 从数据库读取总任务
        session_info = persistence.get_session(session_id)
        original_task = session_info.get('original_task', '') if session_info else ''

        def _is_sub_task_tool_message(messages):
            """启发式检查：最后消息是否为 submit_sub_task 的结果"""
            if not messages or not isinstance(messages[-1], ToolMessage):
                return False
            for i in range(len(messages) - 2, -1, -1):
                msg = messages[i]
                if isinstance(msg, AIMessage):
                    for tc in msg.tool_calls or []:
                        if (tc.get("name") == "submit_sub_task" and
                                tc.get("id") == getattr(messages[-1], "tool_call_id", None)):
                            return True
                    break
            return False

        while True:
            messages = current_state["messages"]

            # ── 恢复检查：如果已处于 waiting_for_input，或消息显示子任务刚完成，跳过图执行 ──
            has_waiting_meta = current_state.get("long_task_meta", {}).get("status") == "waiting_for_input"
            has_tool_waiting = _is_sub_task_tool_message(messages)

            if has_waiting_meta or has_tool_waiting:
                if has_tool_waiting and not has_waiting_meta:
                    self.logger.info(
                        "恢复长任务：通过消息推断子任务已完成，等待用户输入",
                        extra={'tag': 'LONG_TASK_RESUME_WAIT'}
                    )
                    # 补全 meta，保持后续逻辑一致
                    current_state = {**current_state, "long_task_meta": {"status": "waiting_for_input"}}
                    messages = current_state["messages"]
                else:
                    self.logger.info(
                        "恢复长任务：子任务已完成，等待用户输入",
                        extra={'tag': 'LONG_TASK_RESUME_WAIT'}
                    )
            else:
                # 执行一次图（一个子任务）
                final_state = self.graph.invoke(current_state)
                messages = final_state["messages"]
                last_message = messages[-1]

                # 安全检查：最后一条应为 submit_sub_task 返回的 ToolMessage
                if not isinstance(last_message, ToolMessage):
                    self.logger.warning(
                        "长任务异常结束：最后消息不是工具结果，保持运行状态",
                        extra={'tag': 'LONG_TASK_ABNORMAL_END'}
                    )
                    return "任务异常结束。会话保持运行状态，可尝试恢复。"

                # 子任务完成后，显式保存 checkpoint
                checkpoint_state = {
                    "messages": [message_to_dict(m) for m in messages],
                    "consecutive_failures": final_state.get("consecutive_failures", 0),
                    "long_task_meta": {"status": "waiting_for_input"}
                }
                persistence.save_state(session_id, checkpoint_state)
                self.logger.info(
                    "子任务完成，已保存等待输入 checkpoint",
                    extra={'tag': 'LONG_TASK_CHECKPOINT'}
                )

            # ── 获取用户下一个指令（在此退出程序是安全的）──
            sub_task_result = messages[-1].content.strip() if messages[-1].content else ""
            print(f"\n✅ 子任务完成: {sub_task_result}")
            print("-" * 50)
            user_response = input("输入 done 结束任务，q 安全退出并下次恢复，或继续输入新任务:\n> ").strip()

            # 安全退出：不结束任务，保持运行状态以便恢复
            if user_response.lower() in ('q', 'quit', 'exit'):
                self.logger.info("用户选择安全退出，长任务保持运行状态可恢复", extra={'tag': 'LONG_TASK_PAUSE'})
                return "长任务已暂停，输入恢复可继续执行。"

            # 如果用户输入 done，结束长任务
            if user_response.lower() == 'done':
                self.logger.info("用户输入 done，结束长任务", extra={'tag': 'LONG_TASK_END'})
                # 标记会话完成
                if session_id:
                    persistence.mark_completed(session_id)
                self.logger.info("长任务执行完成", extra={'tag': 'TASK_END'})
                return "长任务已完成。"

            # 构造新的 message0：【总任务】+【Current子任务】
            new_message0_content = f"【总任务】{original_task}\n【Current子任务】{user_response}"
            new_message0 = HumanMessage(content=new_message0_content)

            # 构建新状态
            old_messages = messages[1:] if len(messages) > 0 else []
            user_msg = HumanMessage(content=user_response)

            current_state = {
                "messages": [new_message0] + old_messages + [user_msg],
                "consecutive_failures": 0,
                "long_task_meta": {"status": "running"}
            }

            # 保存下一轮初始状态，允许用户在此刻安全退出
            persistence.save_state(session_id, {
                "messages": [message_to_dict(m) for m in current_state["messages"]],
                "consecutive_failures": 0,
                "long_task_meta": {"status": "running"}
            })
            self.logger.info("长任务继续新子任务", extra={'tag': 'LONG_TASK_CONTINUE'})
