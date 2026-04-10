# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage, RemoveMessage
from langchain_core.messages import BaseMessage, AIMessage, message_to_dict
from core.common.state_define import AgentState
from typing import List, Tuple, Dict, Any
from config.configuration import config
from utils.session_persistence import SessionPersistence


def estimate_tokens(text: str) -> int:
    """估算文本的token数量（粗略估算：4字符≈1token）"""
    return len(text) // 4 + 1


def estimate_messages_tokens(messages: List[BaseMessage]) -> int:
    """估算消息列表的总token数"""
    total = 0
    for msg in messages:
        content = getattr(msg, 'content', '') or ''
        total += estimate_tokens(content)
        # 加上消息结构的固定开销
        total += 4
    return total


class ToolNode:
    """
    工具执行节点，包含压缩功能和状态持久化。

    索引转换说明：
    - agent看到的消息包含SystemMessage(索引0)
    - state["messages"]不包含SystemMessage
    - 所以state索引 = agent索引 - 1
    """

    def __init__(self, session_id: int = None, project_directory: str = None):
        self.session_id = session_id
        self.logger = logging.getLogger(__name__)
        self.persistence = SessionPersistence(project_directory) if project_directory else None

    def __call__(self, state: AgentState) -> dict:
        """主入口：执行工具调用"""
        messages = state["messages"]
        tool_calls = state["messages"][-1].tool_calls

        # 获取token限制配置
        context_limit = config.get('model.context_limit', 128000)
        safe_threshold = context_limit - 8000

        tool_results = []
        message_updates = []

        # 计算当前消息的token数
        current_tokens = estimate_messages_tokens(messages)
        self.logger.debug(f"当前消息token估算: {current_tokens}, 安全阈值: {safe_threshold}",
                          extra={'tag': 'TOKEN_CHECK'})

        # 计算历史工具调用次数
        historical_tool_calls = self._count_historical_tool_calls(messages)

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            self.logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})

            if tool_name in ["compress_message", "compress_messages"]:
                result = self._execute_compress_message(messages, tool_call)
                tool_results.extend(result.get("tool_results", []))
                message_updates.extend(result.get("message_updates", []))

            elif tool_name == "compress_paragraph":
                result = self._execute_compress_paragraph(messages, tool_call)
                tool_results.extend(result.get("tool_results", []))
                message_updates.extend(result.get("message_updates", []))

            else:
                result = self._execute_normal_tool(
                    messages, tool_call, current_tokens, safe_threshold, historical_tool_calls
                )
                tool_results.extend(result.get("tool_results", []))
                if result.get("message_updates"):
                    message_updates.extend(result.get("message_updates"))

        # 添加压缩提示（如果需要）
        compress_prompt_msg = self._generate_compress_prompt(messages, historical_tool_calls)
        if compress_prompt_msg:
            tool_results.append(compress_prompt_msg)

        # 保存会话状态
        self._save_session_state(messages, message_updates, tool_results)

        return {"messages": message_updates + tool_results}

    def _count_historical_tool_calls(self, messages: List[BaseMessage]) -> int:
        """计算历史消息中的工具调用次数"""
        count = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                count += len(msg.tool_calls)
        return count

    def _convert_agent_index_to_state(self, agent_idx: int) -> int:
        """将agent看到的索引转换为state索引（减1）"""
        return agent_idx - 1

    def _convert_state_index_to_agent(self, state_idx: int) -> int:
        """将state索引转换为agent看到的索引（加1）"""
        return state_idx + 1

    def _execute_compress_message(self, messages: List[BaseMessage],
                                   tool_call: Dict[str, Any]) -> Dict:
        """执行单条消息压缩工具"""
        tool_results = []
        message_updates = []
        tools_by_name = self._get_tools_by_name()

        try:
            tool = tools_by_name.get(tool_call["name"])
            if tool is None:
                content = f"工具 '{tool_call['name']}' 不存在"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                return {"tool_results": tool_results, "message_updates": message_updates}

            result = tool.invoke(tool_call["args"])
            operations = result.get("operations", []) if isinstance(result, dict) else []

            if not operations:
                content = "单条压缩工具返回空操作列表"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                self.logger.warning(content, extra={'tag': 'COMPRESS_EMPTY'})
                return {"tool_results": tool_results, "message_updates": message_updates}

            # 索引转换：agent索引 -> state索引
            converted_operations = []
            for op in operations:
                agent_idx = op.get("message_index")
                if agent_idx is not None:
                    state_idx = self._convert_agent_index_to_state(agent_idx)
                    # 验证转换后的索引
                    if state_idx < 0:
                        self.logger.error(f"压缩操作：索引{agent_idx}转换为{state_idx}无效（对应SystemMessage）")
                        continue
                    if state_idx == 0:
                        self.logger.error(f"压缩操作：索引{agent_idx}对应用户消息(0)，禁止修改")
                        continue
                    op_copy = op.copy()
                    op_copy["message_index"] = state_idx
                    converted_operations.append(op_copy)

            compression_updates, summary_desc = self._execute_single_compression(
                messages, converted_operations
            )

            if compression_updates:
                message_updates.extend(compression_updates)
                self.logger.info(f"成功单条压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_SUCCESS'})
            else:
                self.logger.warning("单条压缩操作未产生更新", extra={'tag': 'COMPRESS_NO_UPDATE'})

            # 显示时转换回agent索引
            agent_indices = [self._convert_state_index_to_agent(idx) for idx in summary_desc.get("indices", [])]
            display_desc = f"单条压缩：{agent_indices}" if agent_indices else "（无有效单条压缩操作）"
            tool_results.append(ToolMessage(content=display_desc, tool_call_id=tool_call["id"]))

        except Exception as e:
            content = f"单条压缩处理出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'COMPRESS_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _execute_single_compression(self, messages: List[BaseMessage],
                                     operations: List[Dict[str, Any]]) -> Tuple[List[BaseMessage], Dict]:
        """执行单条消息压缩（state索引）"""
        updates = []
        valid_operations = []
        compressed_indices = []

        # 验证操作（state索引）
        for i, op in enumerate(operations):
            state_idx = op.get("message_index")
            op_type = op.get("operation")

            if not isinstance(state_idx, int):
                continue
            # 禁止修改state索引0（用户初始消息）
            if state_idx == 0:
                self.logger.error(f"压缩操作{i}：禁止修改用户消息(0)")
                continue
            if not (0 <= state_idx < len(messages)):
                self.logger.warning(f"压缩操作{i}：索引{state_idx}越界，跳过")
                continue
            if op_type not in ["clear", "summarize"]:
                continue
            if op_type == "summarize" and not op.get("summary_text", "").strip():
                continue

            valid_operations.append((i, state_idx, op_type, op))

        # 按索引从大到小处理
        valid_operations.sort(key=lambda x: x[1], reverse=True)

        for op_idx, state_idx, op_type, op in valid_operations:
            target_msg = messages[state_idx]

            try:
                if op_type == "summarize":
                    summary = op.get("summary_text", "").strip()
                    new_content = summary if summary else "[摘要]"
                else:  # clear
                    new_content = ""

                if isinstance(target_msg, ToolMessage):
                    new_msg = ToolMessage(
                        content=new_content,
                        tool_call_id=target_msg.tool_call_id,
                        id=target_msg.id,
                        additional_kwargs={
                            **getattr(target_msg, "additional_kwargs", {}),
                            "original_index": state_idx,
                            "compressed": True
                        }
                    )
                    updates.append(new_msg)
                    self.logger.info(f"单条压缩{op_idx}：state索引{state_idx} ToolMessage {'摘要' if op_type == 'summarize' else '清空'}")

                elif isinstance(target_msg, AIMessage):
                    new_msg = AIMessage(
                        content=new_content,
                        id=target_msg.id,
                        tool_calls=getattr(target_msg, "tool_calls", None),
                        additional_kwargs={
                            **getattr(target_msg, "additional_kwargs", {}),
                            "original_index": state_idx,
                            "compressed": True
                        }
                    )
                    updates.append(new_msg)
                    self.logger.info(f"单条压缩{op_idx}：state索引{state_idx} AIMessage {'摘要' if op_type == 'summarize' else '清空'}")

                else:
                    target_msg.content = new_content
                    target_msg.additional_kwargs = {
                        **getattr(target_msg, "additional_kwargs", {}),
                        "original_index": state_idx,
                        "compressed": True
                    }
                    updates.append(target_msg)
                    self.logger.info(f"单条压缩{op_idx}：state索引{state_idx} {type(target_msg).__name__} {'摘要' if op_type == 'summarize' else '清空'}")

                compressed_indices.append(state_idx)

            except Exception as e:
                self.logger.error(f"单条压缩操作{op_idx}执行失败: {e}")

        return updates, {"indices": compressed_indices}

    def _execute_compress_paragraph(self, messages: List[BaseMessage],
                                     tool_call: Dict[str, Any]) -> Dict:
        """执行段落压缩工具"""
        tool_results = []
        message_updates = []
        tools_by_name = self._get_tools_by_name()
        args = tool_call["args"]

        try:
            # 段落压缩限制：agent看到的消息数必须超过20条（state实际 > 19条即state >= 20条）
            if len(messages) < 20:
                content = f"段落压缩拒绝：当前消息数 {len(messages)} 条，未达到 20 条的最低要求。请先使用单条压缩工具进行压缩。"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                self.logger.warning(f"段落压缩被拒绝：消息数{len(messages)}<20", extra={'tag': 'COMPRESS_PARAGRAPH_DENIED'})
                return {"tool_results": tool_results, "message_updates": message_updates}

            tool = tools_by_name.get("compress_paragraph")
            if tool is None:
                content = "工具 'compress_paragraph' 不存在"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                return {"tool_results": tool_results, "message_updates": message_updates}

            result = tool.invoke(args)
            if not isinstance(result, dict) or not result.get("valid"):
                content = result.get("message", "段落压缩参数无效") if isinstance(result, dict) else "段落压缩返回无效结果"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                self.logger.warning(content, extra={'tag': 'COMPRESS_PARAGRAPH_INVALID'})
                return {"tool_results": tool_results, "message_updates": message_updates}

            # 索引转换：agent索引 -> state索引
            agent_start_idx = result.get("start_index")
            agent_end_idx = result.get("end_index")
            state_start_idx = self._convert_agent_index_to_state(agent_start_idx)
            state_end_idx = self._convert_agent_index_to_state(agent_end_idx)

            compression_updates, summary_desc = self._execute_paragraph_compression(
                messages, state_start_idx, state_end_idx, result.get("summary")
            )

            if compression_updates:
                message_updates.extend(compression_updates)
                self.logger.info(f"成功段落压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_PARAGRAPH_SUCCESS'})
            else:
                self.logger.warning(f"段落压缩操作未产生更新: {summary_desc}", extra={'tag': 'COMPRESS_PARAGRAPH_NO_UPDATE'})

            # 显示时转换回agent索引
            agent_range = f"{agent_start_idx}-{agent_end_idx}"
            display_desc = f"段落压缩：{agent_range}替换为总结"
            tool_results.append(ToolMessage(content=display_desc, tool_call_id=tool_call["id"]))

        except Exception as e:
            content = f"段落压缩处理出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'COMPRESS_PARAGRAPH_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _execute_paragraph_compression(self, messages: List[BaseMessage],
                                        start_idx: int, end_idx: int,
                                        summary_text: str) -> Tuple[List[BaseMessage], str]:
        """执行段落压缩（state索引）"""
        updates = []

        # 验证参数
        if not isinstance(start_idx, int) or not isinstance(end_idx, int):
            return [], "段落压缩失败：start_index和end_index必须是整数"
        if not summary_text or not summary_text.strip():
            return [], "段落压缩失败：summary不能为空"
        # 禁止修改state索引0（用户初始消息）
        if start_idx <= 0 or end_idx <= 0:
            self.logger.error(f"段落压缩：禁止包含用户消息(0)")
            return [], "段落压缩失败：禁止包含用户消息(0)"
        if not (0 <= start_idx < len(messages) and 0 <= end_idx < len(messages)):
            self.logger.warning(f"段落压缩：索引越界")
            return [], "段落压缩失败：索引越界"
        if start_idx >= end_idx:
            return [], "段落压缩失败：start_index必须小于end_index"

        # 验证成对约束
        tool_related_msgs = []
        for idx in range(start_idx, end_idx + 1):
            msg = messages[idx]
            is_tool_call = isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
            is_tool_result = isinstance(msg, ToolMessage)
            if is_tool_call or is_tool_result:
                tool_related_msgs.append((idx, msg, is_tool_call))

        # 必须至少有一对工具相关消息
        if not tool_related_msgs:
            return [], f"段落压缩失败：范围{start_idx}-{end_idx}内没有找到工具相关消息（AIMessage+tool_calls或ToolMessage）"

        # 第一个工具相关消息必须是 AIMessage+tool_calls
        first_idx, first_msg, first_is_tool_call = tool_related_msgs[0]
        if not first_is_tool_call:
            return [], f"段落压缩失败：范围内第一个工具相关消息（state索引{first_idx}）必须是AIMessage且有tool_calls"

        # 最后一个工具相关消息必须是 ToolMessage
        last_idx, last_msg, last_is_tool_call = tool_related_msgs[-1]
        if last_is_tool_call:
            return [], f"段落压缩失败：范围内最后一个工具相关消息（state索引{last_idx}）必须是ToolMessage"

        try:
            # 使用 start_idx 消息的ID创建总结消息
            first_msg = messages[start_idx]
            summary_msg = AIMessage(
                content=f"[段落总结] {summary_text}",
                id=first_msg.id,
                tool_calls=None,
                additional_kwargs={
                    **getattr(first_msg, "additional_kwargs", {}),
                    "compressed": True,
                    "is_paragraph_summary": True,
                    "original_range": f"{start_idx}-{end_idx}"
                }
            )
            updates.append(summary_msg)

            # 删除其余消息
            for idx in range(start_idx + 1, end_idx + 1):
                target_msg = messages[idx]
                updates.append(RemoveMessage(id=target_msg.id))

            self.logger.info(f"段落压缩：state索引{start_idx}-{end_idx}已替换为总结")
            return updates, f"段落压缩：{start_idx}-{end_idx}替换为总结"

        except Exception as e:
            self.logger.error(f"段落压缩执行失败: {e}")
            return [], f"段落压缩失败: {e}"

    def _execute_normal_tool(self, messages: List[BaseMessage],
                              tool_call: Dict[str, Any],
                              current_tokens: int,
                              safe_threshold: int,
                              historical_tool_calls: int) -> Dict:
        """执行普通工具"""
        tool_results = []
        message_updates = []
        tools_by_name = self._get_tools_by_name()
        tool_name = tool_call["name"]

        try:
            tool = tools_by_name.get(tool_name)
            if tool is None:
                content = f"工具 '{tool_name}' 不存在"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                return {"tool_results": tool_results, "message_updates": message_updates}

            content = tool.invoke(tool_call["args"])

            # 检查token上限
            content_tokens = estimate_tokens(str(content))
            projected_tokens = current_tokens + content_tokens

            if projected_tokens > safe_threshold:
                overflow = projected_tokens - config.get('model.context_limit', 128000)
                warning_content = "【系统提示】当前上下文已接近Token上限，请立即调用压缩工具压缩上下文后再继续。"
                tool_results.append(ToolMessage(content=warning_content, tool_call_id=tool_call["id"]))
                self.logger.warning(f"触发Token上限提示: {projected_tokens}>{safe_threshold}", extra={'tag': 'TOKEN_PROMPT'})
            else:
                tool_results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
                self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})

                # 大结果提示
                if content_tokens > 1000 and historical_tool_calls > 5:
                    large_result_prompt = (
                        f"【系统提示】上一个工具调用产生了较大的结果（约{content_tokens} token）。"
                        f"如果你只需要该结果的部分内容（<30%的连续片段），"
                        f"请使用单条压缩工具对该结果进行摘要或清空。"
                    )
                    message_updates.append(HumanMessage(content=large_result_prompt))
                    self.logger.info(f"大结果提示: 工具{tool_name}返回{content_tokens}token", extra={'tag': 'LARGE_RESULT_PROMPT'})

        except Exception as e:
            content = f"工具 {tool_name} 执行出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'TOOL_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _generate_compress_prompt(self, messages: List[BaseMessage],
                                   historical_tool_calls: int) -> HumanMessage:
        """生成压缩提示消息（如果需要）"""
        message_count = len(messages)

        # 优先级1：消息数量超过100条
        if message_count >= 100:
            has_msg_count_prompt = any(
                isinstance(msg, HumanMessage) and msg.content.startswith("【系统提示】当前对话消息数")
                for msg in messages
            )
            if not has_msg_count_prompt:
                self.logger.info(f"触发消息数量压缩提示({message_count}条消息)", extra={'tag': 'COMPRESS_MSG_COUNT'})
                return HumanMessage(
                    content=f"【系统提示】当前对话消息数已达{message_count}条，已超过100条。请立即调用压缩工具压缩上下文后再继续。"
                )

        # 优先级2：每5次工具调用后
        if historical_tool_calls % 5 == 0 and historical_tool_calls > 0:
            has_compress_prompt = any(
                isinstance(msg, HumanMessage) and msg.content.startswith("【系统提示】已进行")
                for msg in messages
            )
            if not has_compress_prompt:
                self.logger.info(f"触发压缩评估提示(累计{historical_tool_calls}次工具调用)", extra={'tag': 'COMPRESS_PROMPT'})
                return HumanMessage(
                    content=f"【系统提示】已进行{historical_tool_calls}次工具调用，请评估是否需要压缩上下文"
                )

        return None

    def _save_session_state(self, messages: List[BaseMessage],
                            message_updates: List[BaseMessage],
                            tool_results: List[BaseMessage]):
        """保存会话状态到持久化存储"""
        if self.persistence and self.session_id:
            try:
                all_messages = messages + message_updates + tool_results
                state_to_save = {
                    "messages": [message_to_dict(m) for m in all_messages]
                }
                self.persistence.save_state(self.session_id, state_to_save)
                self.logger.debug(f"会话状态已保存: session_id={self.session_id}", extra={'tag': 'STATE_SAVED'})
            except Exception as e:
                self.logger.error(f"保存会话状态失败: {e}", extra={'tag': 'STATE_SAVE_ERROR'})

    def _get_tools_by_name(self):
        """延迟导入工具，避免循环导入"""
        from tools import tools_by_name
        return tools_by_name


# 保持向后兼容的函数接口
def create_tool_node(session_id: int = None,
                     project_directory: str = None) -> ToolNode:
    """
    创建工具执行节点（工厂函数，保持向后兼容）。
    """
    return ToolNode(session_id, project_directory)
