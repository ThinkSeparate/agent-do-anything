# core/react/agent.py
import os
import logging
from langchain.messages import HumanMessage, ToolMessage, AIMessage, RemoveMessage
from utils.token_utils import estimate_tokens, estimate_messages_tokens
from langchain_core.messages import messages_from_dict, BaseMessage, AIMessage as AIMessageCore
from config.configuration import config


def auto_compress_messages(messages: list) -> tuple:
    """
    Auto-compress message list.
    Strategy: Keep recent 10 messages, compress older ones while maintaining tool call chain integrity.
    Returns: (new_message_list, compression_description)
    """
    if len(messages) <= 10:
        return messages, "Too few messages, no compression needed"

    # Scan all messages to identify tool call chain positions
    protected_indices = set()

    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessageCore) and getattr(msg, "tool_calls", None):
            tool_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
            for j in range(i + 1, len(messages)):
                if isinstance(messages[j], ToolMessage):
                    if messages[j].tool_call_id in tool_call_ids:
                        protected_indices.add(i)
                        protected_indices.add(j)
                        tool_call_ids.discard(messages[j].tool_call_id)
                    if not tool_call_ids:
                        break

    keep_count = 10
    start_idx = len(messages) - keep_count

    for i in range(start_idx, len(messages)):
        protected_indices.add(i)

    while start_idx > 0 and any(idx >= start_idx and idx < start_idx + keep_count for idx in protected_indices):
        start_idx -= 1

    recent_messages = messages[start_idx:]
    old_messages = messages[:start_idx]

    compressed_count = 0

    for msg in old_messages:
        if isinstance(msg, ToolMessage):
            msg.content = "[COMPRESSED:tool result]"
            msg.additional_kwargs = {**getattr(msg, "additional_kwargs", {}), "compressed": True}
            compressed_count += 1
        elif isinstance(msg, AIMessageCore):
            if getattr(msg, "tool_calls", None):
                msg.content = "[COMPRESSED:tool call]"
                msg.additional_kwargs = {**getattr(msg, "additional_kwargs", {}), "compressed": True}
            else:
                msg.content = "[COMPRESSED]"
                msg.additional_kwargs = {**getattr(msg, "additional_kwargs", {}), "compressed": True}
            compressed_count += 1
        elif isinstance(msg, HumanMessage):
            msg.content = "[COMPRESSED:user input]"
            msg.additional_kwargs = {**getattr(msg, "additional_kwargs", {}), "compressed": True}
            compressed_count += 1

    old_tokens = estimate_messages_tokens(messages)
    new_tokens = estimate_messages_tokens(old_messages + recent_messages)
    saved_tokens = old_tokens - new_tokens

    desc = f"Auto-compression: processed {compressed_count} old messages, kept {len(recent_messages)} messages, saved ~{saved_tokens} tokens"
    return old_messages + recent_messages, desc


def check_and_compress_on_resume(messages: list, logger) -> list:
    """Check token on resume and auto-compress if needed."""
    context_limit = config.get("model.context_limit", 128000)
    token_buffer = config.get("model.token_buffer", int(context_limit * 0.2))
    safe_threshold = context_limit - token_buffer

    current_tokens = estimate_messages_tokens(messages)

    if current_tokens > safe_threshold:
        logger.warning(f"Token check on resume: {current_tokens} > {safe_threshold}, auto-compressing",
                      extra={"tag": "RESUME_COMPRESS"})
        messages, desc = auto_compress_messages(messages)
        logger.info(desc, extra={"tag": "RESUME_COMPRESS"})
        new_tokens = estimate_messages_tokens(messages)
        logger.info(f"After compression: ~{new_tokens} tokens", extra={"tag": "RESUME_COMPRESS"})
    else:
        logger.info(f"Token check on resume: {current_tokens} tokens, safe", extra={"tag": "RESUME_CHECK"})

    return messages


def validate_and_fix_messages(messages):
    """Validate and fix messages to ensure tool call integrity."""
    logger = logging.getLogger(__name__)
    valid_tool_call_ids = set()

    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("id"):
                    valid_tool_call_ids.add(tc["id"])

    tool_msg_ids = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                tool_msg_ids.add(msg.tool_call_id)

    fixed_messages = []
    removed_count = 0
    fixed_tool_calls_count = 0

    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            if not hasattr(msg, "tool_call_id") or msg.tool_call_id not in valid_tool_call_ids:
                logger.warning(f"Remove orphaned ToolMessage (index {i})", extra={"tag": "MSG_FIX"})
                removed_count += 1
                continue
        elif isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            missing = [tc.get("id") for tc in msg.tool_calls if tc.get("id") and tc.get("id") not in tool_msg_ids]
            if missing:
                logger.warning(f"Fix AIMessage (index {i}): missing tool responses", extra={"tag": "MSG_FIX"})
                msg = AIMessage(content=msg.content, id=msg.id,
                              additional_kwargs={**getattr(msg, "additional_kwargs", {}), "tool_calls_removed": True})
                fixed_tool_calls_count += 1
        fixed_messages.append(msg)

    if removed_count > 0 or fixed_tool_calls_count > 0:
        logger.info(f"Message validation: removed {removed_count}, fixed {fixed_tool_calls_count}",
                   extra={"tag": "MSG_VALIDATED"})

    return fixed_messages


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

    def __init__(self, project_directory: str, task_mode: str = 'short'):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"ReActAgent 初始化开始 (模式: {task_mode})", extra={'tag': 'AGENT_INIT'})
        self.project_directory = project_directory
        self.task_mode = task_mode

        # 0. 使用公共函数加载配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'model.timeout', 'agent.output_root']
        agent_utils.load_agent_config(required_keys)

        # 从配置中读取路径
        self.agent_output_root = agent_utils.get_agent_output_root(self.project_directory, config.get('agent.output_root'))
        configure_agent_output_root(lambda: self.agent_output_root)
        self.logger.info(f"已从配置加载safe写入目录: {self.agent_output_root}", extra={'tag': 'AGENT_INIT'})

        # 1. 准备模型配置
        model_keys = {
            'model_name': config.get('model.name'),
            'base_url': config.get('model.base_url'),
            'api_key': config.get('model.api_key'),
            'timeout': config.get('model.timeout'),
        }

        # 2. 使用公共函数创建模型（绑定工具，根据 task_mode 动态选择）
        self.model_with_tools = agent_utils.create_agent_model(
            model_keys=model_keys,
            tools_getter=lambda: get_react_tools(task_mode=task_mode)
        )

        # 3. 使用公共函数渲染系统提示
        context_limit = config.get('model.context_limit', 128000)
        compress_threshold = config.get('model.context_compress_threshold', 100000)

        # 根据模式选择结束工具名称和描述
        if task_mode == 'long':
            task_end_tool = 'wait_for_next_task'
            task_end_description = '''    - **当你完成Current步骤或需要用户进一步指示时，调用 `${task_end_tool}` 工具。** 调用此工具后，你将等待用户的下一步输入，任务不会结束，而是进入下一个迭代周期。'''
            task_end_rule = '''**只有 `${task_end_tool}` 工具能正式暂停任务等待用户输入。** 不要在思考中直接写出答案，也不要用其他工具来返回答案。长任务模式下，你将多次与用户交互直到用户输入 "done" 结束任务。'''
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
                # 验证并修复消息（移除孤立的ToolMessage）
                messages = validate_and_fix_messages(messages)
                # 【新增】恢复时检查token，必要时自动压缩
                messages = check_and_compress_on_resume(messages, self.logger)
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

        current_state = initial_state
        sub_task_count = 0

        # 从数据库读取总任务
        session_info = persistence.get_session(session_id)
        original_task = session_info.get('original_task', '') if session_info else ''

        while True:
            # 执行一次图
            final_state = self.graph.invoke(current_state)

            messages = final_state["messages"]
            last_message = messages[-1]

            # 检查是否是 wait_for_next_task 返回的结果
            # wait_for_next_task 工具返回的内容包含用户的输入
            if last_message.content:
                user_response = last_message.content.strip()

                # 如果用户输入 done，结束长任务
                if user_response.lower() == 'done':
                    self.logger.info("用户输入 done，结束长任务", extra={'tag': 'LONG_TASK_END'})
                    # 标记会话完成
                    if session_id:
                        persistence.mark_completed(session_id)
                    self.logger.info(f"长任务执行完成，共 {sub_task_count} 个子任务",
                                    extra={'tag': 'TASK_END'})
                    return f"长任务已完成。共执行 {sub_task_count} 个子任务。"

                # 否则，将用户响应作为新任务继续
                sub_task_count += 1
                self.logger.info(f"继续长任务第 {sub_task_count} 个子任务",
                               extra={'tag': 'LONG_TASK_CONTINUE'})

                # 构造新的 message0：【总任务】+【Current子任务】
                new_message0_content = f"【总任务】{original_task}\n【Current子任务】{user_response}"
                new_message0 = HumanMessage(content=new_message0_content)

                # 构建新状态：
                # [0] 新的 message0（替换原消息）
                # [1..n] 原消息（Kept所有历史，包括之前的 tool_calls 和 ToolMessage）
                # [新] HumanMessage: 用户新输入作为下一个子任务
                old_messages = messages[1:] if len(messages) > 0 else []

                # 用户新输入作为 HumanMessage
                user_msg = HumanMessage(content=user_response)

                new_messages = [new_message0] + old_messages + [user_msg]

                current_state = {
                    "messages": new_messages,
                    "consecutive_failures": 0,
                }
                continue
            else:
                # 没有返回内容，可能是异常情况，不标记完成，保持run状态
                self.logger.warning("长任务异常结束：没有返回内容", extra={'tag': 'LONG_TASK_ABNORMAL_END'})
                return "任务异常结束。会话保持运行状态，可尝试恢复。"
