# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage, RemoveMessage
from langchain_core.messages import BaseMessage, AIMessage, message_to_dict
from core.common.state_define import AgentState
from typing import List, Tuple, Dict, Any
from config.configuration import config
from utils.token_utils import estimate_tokens
from utils.session_persistence import SessionPersistence


class ToolNode:
    """
    工具执行节点，包含压缩功能和状态持久化。
    所有索引均使用 msg.index，不再进行转换。
    """

    def __init__(self, session_id: int = None, project_directory: str = None):
        self.session_id = session_id
        self.logger = logging.getLogger(__name__)
        self.persistence = SessionPersistence(project_directory) if project_directory else None

    def _assign_index_to_messages(self, messages: List[BaseMessage], existing_messages: List[BaseMessage]) -> int:
        """为新消息分配索引，基于现有消息的最大索引"""
        max_idx = 0
        for msg in existing_messages:
            if hasattr(msg, 'index') and msg.index is not None:
                max_idx = max(max_idx, msg.index)

        for msg in messages:
            if not hasattr(msg, 'index') or msg.index is None:
                max_idx += 1
                msg.index = max_idx

        return max_idx

    def _find_msg_by_index(self, messages: List[BaseMessage], target_index: int) -> Tuple[int, BaseMessage]:
        """通过 index 查找消息，返回 (position, msg)"""
        for pos, msg in enumerate(messages):
            if getattr(msg, 'index', None) == target_index:
                return pos, msg
        return -1, None

    def __call__(self, state: AgentState) -> dict:
        """主入口：执行工具调用"""
        messages = state["messages"]
        tool_calls = state["messages"][-1].tool_calls

        tool_results = []
        message_updates = []

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            self.logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})

            if tool_name == "compress_messages":
                result = self._execute_compress_message(messages, tool_call)
                tool_results.extend(result.get("tool_results", []))
                message_updates.extend(result.get("message_updates", []))

            elif tool_name == "compress_paragraph":
                result = self._execute_compress_paragraph(messages, tool_call)
                tool_results.extend(result.get("tool_results", []))
                message_updates.extend(result.get("message_updates", []))

            else:
                result = self._execute_normal_tool(messages, tool_call)
                tool_results.extend(result.get("tool_results", []))
                if result.get("message_updates"):
                    message_updates.extend(result.get("message_updates"))

        # 应用消息更新（压缩、删除等）到原始消息列表
        updated_messages = self._apply_message_updates(messages, message_updates)

        # 为新消息分配索引
        all_new_messages = tool_results + message_updates
        self._assign_index_to_messages(all_new_messages, messages)

        # 保存会话状态
        self._save_session_state(updated_messages, message_updates, tool_results)

        # 返回工具结果和更新指令（RemoveMessage等）
        # 注意：message_updates 包含 RemoveMessage 等更新指令，需要传递下去让框架处理
        return {"messages": tool_results + message_updates}

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

            # 按索引从大到小处理（避免删除影响后续索引）
            valid_operations = sorted(operations, key=lambda e: e.get("index", -1), reverse=True)

            compression_updates = []
            compressed_indices = []
            error_infos = []

            for op_idx, op in enumerate(valid_operations):
                target_idx = op.get("index", -1)

                if target_idx <= 0:
                    error_infos.append({"idx": target_idx, "reason": "索引必须>=1"})
                    continue
                if target_idx == 1:
                    error_infos.append({"idx": target_idx, "reason": "禁止修改用户初始任务(index:1)"})
                    continue

                # 通过 index 查找消息
                pos, target_msg = self._find_msg_by_index(messages, target_idx)
                if pos < 0 or target_msg is None:
                    error_infos.append({"idx": target_idx, "reason": "索引不存在"})
                    continue

                op_type = op.get("operation")

                try:
                    if op_type == "summarize":
                        summary = op.get("summary_text", "").strip()
                        new_content = summary if summary else "[摘要]"
                    elif op_type == "clear":
                        new_content = ""
                    else:
                        error_infos.append({"idx": target_idx, "reason": f"无效的操作{op_type}"})
                        continue

                    new_msg = self._gen_new_msg(target_msg, new_content, operation_type=op_type)
                    compression_updates.append(new_msg)
                    compressed_indices.append(target_idx)
                    msg_type = type(target_msg).__name__
                    self.logger.info(f"单条压缩{op_idx}：index:{target_idx} {msg_type} {'摘要' if op_type == 'summarize' else '清空'}")

                except Exception as e:
                    self.logger.error(f"单条压缩执行失败(index:{target_idx}): {e}")
                    error_infos.append({"idx": target_idx, "reason": f"执行失败: {e}"})

            if compression_updates:
                message_updates.extend(compression_updates)
                self.logger.info(f"成功单条压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_SUCCESS'})
            else:
                self.logger.warning("单条压缩操作未产生更新", extra={'tag': 'COMPRESS_NO_UPDATE'})

            parts = []
            if compressed_indices:
                parts.append(f"成功压缩索引：{compressed_indices}")
            if error_infos:
                error_list = ",".join([f"{e['idx']}: {e['reason']}" for e in error_infos])
                self.logger.warning(f"压缩失败列表: {error_list}")
                parts.append(f"失败：{error_list}")
            display_desc = "; ".join(parts) if parts else "（无有效单条压缩操作）"

            tool_results.append(ToolMessage(content=display_desc, tool_call_id=tool_call["id"]))

        except Exception as e:
            content = f"单条压缩处理出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'COMPRESS_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _gen_new_msg(self, target_msg, new_content, operation_type: str = None):
        """
        生成压缩后的新消息，保持 index 不变，只更新 content。

        Args:
            target_msg: 目标消息
            new_content: 新内容
            operation_type: 操作类型，"clear" 或 "summarize"
                           clear 操作会清除 tool_calls 以节省 token
        """
        original_index = getattr(target_msg, 'index', None)

        kwargs = {
            "content": new_content,
            "additional_kwargs": {
                **getattr(target_msg, "additional_kwargs", {}),
                "compressed": True
            }
        }

        if isinstance(target_msg, ToolMessage):
            new_msg = ToolMessage(
                tool_call_id=target_msg.tool_call_id,
                id=target_msg.id,
                **kwargs
            )
        elif isinstance(target_msg, AIMessage):
            # 【关键】保留 tool_calls 结构但清空 args 以节省 token
            # 验证逻辑只检查 id，清空 args 不会导致 ToolMessage 被丢弃
            original_tool_calls = getattr(target_msg, "tool_calls", None) or []
            if original_tool_calls and operation_type in ("clear", "summarize"):
                # 保留 id 和 name，清空 args
                cleared_tool_calls = [
                    {**tc, "args": {"_compressed": True}}
                    for tc in original_tool_calls
                ]
            else:
                cleared_tool_calls = original_tool_calls

            new_msg = AIMessage(
                id=target_msg.id,
                tool_calls=cleared_tool_calls,
                **kwargs
            )
        else:
            target_msg.content = new_content
            target_msg.additional_kwargs = kwargs["additional_kwargs"]
            return target_msg

        if original_index is not None:
            new_msg.index = original_index
        return new_msg

    def _execute_compress_paragraph(self, messages: List[BaseMessage],
                                     tool_call: Dict[str, Any]) -> Dict:
        """执行段落压缩工具"""
        tool_results = []
        message_updates = []
        tools_by_name = self._get_tools_by_name()
        args = tool_call["args"]

        try:
            if len(messages) < 20:
                content = f"段落压缩拒绝：当前消息数 {len(messages)} 条，未达到 20 条的最低要求。"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                self.logger.warning(f"段落压缩被拒绝：消息数{len(messages)}<20", extra={'tag': 'COMPRESS_PARAGRAPH_DENIED'})
                return {"tool_results": tool_results, "message_updates": message_updates}

            result = tools_by_name["compress_paragraph"].invoke(args)
            if not isinstance(result, dict) or not result.get("valid"):
                content = result.get("message", "段落压缩参数无效") if isinstance(result, dict) else "段落压缩返回无效结果"
                tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                self.logger.warning(content, extra={'tag': 'COMPRESS_PARAGRAPH_INVALID'})
                return {"tool_results": tool_results, "message_updates": message_updates}

            # 直接使用返回的索引（已经是 msg.index）
            start_idx = result.get("start_index")
            end_idx = result.get("end_index")

            compression_updates, summary_desc = self._execute_paragraph_compression(
                messages, start_idx, end_idx, result.get("summary")
            )

            if compression_updates:
                message_updates.extend(compression_updates)
                self.logger.info(f"成功段落压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_PARAGRAPH_SUCCESS'})
                display_desc = f"段落压缩：{start_idx}-{end_idx}替换为总结"
                tool_results.append(ToolMessage(content=display_desc, tool_call_id=tool_call["id"]))
            else:
                error_msg = f"段落压缩未生效: {summary_desc}"
                tool_results.append(ToolMessage(content=error_msg, tool_call_id=tool_call["id"]))
                self.logger.warning(error_msg, extra={'tag': 'COMPRESS_PARAGRAPH_NO_UPDATE'})

        except Exception as e:
            content = f"段落压缩处理出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'COMPRESS_PARAGRAPH_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _execute_paragraph_compression(self, messages: List[BaseMessage],
                                        start_idx: int, end_idx: int,
                                        summary_text: str) -> Tuple[List[BaseMessage], str]:
        """执行段落压缩，使用 msg.index 验证范围"""
        updates = []

        if not isinstance(start_idx, int) or not isinstance(end_idx, int):
            return [], "段落压缩失败：start_index和end_index必须是整数"
        if not summary_text or not summary_text.strip():
            return [], "段落压缩失败：summary不能为空"
        if start_idx <= 1 or end_idx <= 1:
            return [], "段落压缩失败：禁止包含index:1(用户初始任务)"
        if start_idx >= end_idx:
            return [], "段落压缩失败：start_index必须小于end_index"

        # 收集目标索引范围内的消息
        target_msgs = []
        for msg in messages:
            msg_idx = getattr(msg, 'index', None)
            if msg_idx is not None and start_idx <= msg_idx <= end_idx:
                target_msgs.append(msg)

        if not target_msgs:
            return [], f"段落压缩失败：范围{start_idx}-{end_idx}内没有找到消息"

        # 验证成对约束：第一个必须是AIMessage+tool_calls，最后一个必须是ToolMessage
        tool_related_msgs = []
        for msg in target_msgs:
            is_tool_call = isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
            is_tool_result = isinstance(msg, ToolMessage)
            if is_tool_call or is_tool_result:
                tool_related_msgs.append((msg, is_tool_call))

        if not tool_related_msgs:
            return [], f"段落压缩失败：范围{start_idx}-{end_idx}内没有工具相关消息"

        first_msg, first_is_tool_call = tool_related_msgs[0]
        if not first_is_tool_call:
            first_idx = getattr(first_msg, 'index', '?')
            return [], f"段落压缩失败：范围内第一个工具相关消息index:{first_idx}必须是AIMessage且有tool_calls"

        last_msg, last_is_tool_call = tool_related_msgs[-1]
        if last_is_tool_call:
            last_idx = getattr(last_msg, 'index', '?')
            return [], f"段落压缩失败：范围内最后一个工具相关消息index:{last_idx}必须是ToolMessage"

        try:
            # 使用第一个消息的ID创建总结消息，继承其index
            first_msg_index = getattr(first_msg, 'index', None)

            summary_msg = AIMessage(
                content=f"[段落总结] {summary_text}",
                id=first_msg.id,
                tool_calls=[],
                additional_kwargs={
                    **getattr(first_msg, "additional_kwargs", {}),
                    "compressed": True,
                    "is_paragraph_summary": True,
                    "original_range": f"{start_idx}-{end_idx}"
                }
            )
            if first_msg_index is not None:
                summary_msg.index = first_msg_index
            updates.append(summary_msg)

            # 删除其余消息（除了第一个，也就是 summary_msg 替换的那个）
            for msg in target_msgs:
                if msg is not first_msg:
                    updates.append(RemoveMessage(id=msg.id))

            self.logger.info(f"段落压缩：index:{start_idx}-{end_idx}已替换为总结")
            return updates, f"段落压缩：{start_idx}-{end_idx}替换为总结"

        except Exception as e:
            self.logger.error(f"段落压缩执行失败: {e}")
            return [], f"段落压缩失败: {e}"

    def _execute_normal_tool(self, messages: List[BaseMessage],
                              tool_call: Dict[str, Any]) -> Dict:
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
            tool_results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
            self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})

        except Exception as e:
            content = f"工具 {tool_name} 执行出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'TOOL_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

    def _apply_message_updates(self, messages: List[BaseMessage],
                               message_updates: List[BaseMessage]) -> List[BaseMessage]:
        """
        将消息更新应用到消息列表。
        - RemoveMessage: 从列表中删除对应 id 的消息
        - 其他消息（如压缩后的消息）：替换列表中同 id 的消息
        """
        if not message_updates:
            return messages

        # 创建消息 id 到位置的映射
        msg_dict = {getattr(m, 'id', None): i for i, m in enumerate(messages) if getattr(m, 'id', None)}

        # 要删除的消息 id 集合
        to_remove_ids = set()
        # 要更新的消息（id -> 新消息）
        to_update = {}

        for update_msg in message_updates:
            if isinstance(update_msg, RemoveMessage):
                # RemoveMessage 的 id 是要删除的消息的 id
                to_remove_ids.add(update_msg.id)
            elif hasattr(update_msg, 'id') and update_msg.id:
                # 其他消息（如压缩后的消息）按 id 更新
                to_update[update_msg.id] = update_msg

        # 构建新的消息列表
        new_messages = []
        for msg in messages:
            msg_id = getattr(msg, 'id', None)
            if msg_id in to_remove_ids:
                # 跳过被删除的消息
                continue
            if msg_id in to_update:
                # 用新消息替换
                new_messages.append(to_update[msg_id])
                del to_update[msg_id]  # 标记为已处理
            else:
                new_messages.append(msg)

        return new_messages

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
