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

        # 【已移除】压缩提示已移动到 model_node.py 统一处理
        # 包括：消息数量提示、每5次调用提示、大结果提示

        # 保存会话状态
        self._save_session_state(messages, message_updates, tool_results)

        # 注意顺序：必须先返回 tool_results（ToolMessage 响应当前 tool_call），
        # 然后才是 message_updates（额外的系统提示等）
        return {"messages": tool_results + message_updates}

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

            """执行单条消息压缩（state索引）"""
            # 按索引从大到小处理
            valid_operations = sorted(operations, key=lambda e: e.get("message_index", -1), reverse=True)

            compression_updates = []
            compressed_indices = []
            error_infos = []
            for op_idx, op in enumerate(valid_operations):
                agent_idx = op.get("message_index", -1)
                if agent_idx < 0:
                    error_infos.append({"idx": agent_idx, "reason": "索引不能为空，或者<0"})
                    continue
                if agent_idx == 0:
                    error_infos.append({"idx": agent_idx, "reason": "禁止修改系统消息"})
                    continue
                if agent_idx == 1:
                    error_infos.append({"idx": agent_idx, "reason": "禁止修改用户初始任务"})
                    continue

                state_idx = self._convert_agent_index_to_state(agent_idx)
                op_type = op.get("operation")

                if not (0 <= state_idx < len(messages)):
                    error_infos.append({"idx": agent_idx, "reason": "索引越界"})
                    continue

                target_msg = messages[state_idx]

                try:
                    if op_type == "summarize":
                        summary = op.get("summary_text", "").strip()
                        new_content = summary if summary else "[摘要]"
                    elif op_type == "clear":
                        new_content = ""
                    else:
                        error_infos.append({"idx": agent_idx, "reason": f"无效的操作{op_type}"})
                        continue

                    new_msg = self._gen_new_msg(state_idx, op_type, target_msg, new_content)
                    compression_updates.append(new_msg)
                    compressed_indices.append(agent_idx)
                    msg_type = type(target_msg).__name__
                    self.logger.info(f"单条压缩{op_idx}：agent索引{agent_idx} {msg_type} {'摘要' if op_type == 'summarize' else '清空'}")

                except Exception as e:
                    self.logger.error(f"单条压缩执行失败(索引{agent_idx}): {e}")
                    error_infos.append({"idx": agent_idx, "reason": f"执行失败: {e}"})
                
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

    def _gen_new_msg(self, state_idx, op_type, target_msg, new_content):
        kwargs = {
            "content": new_content,
            "additional_kwargs": {
                **getattr(target_msg, "additional_kwargs", {}),
                "original_index": state_idx,
                "compressed": True
            }
        }
        if isinstance(target_msg, ToolMessage):
            return ToolMessage(
                tool_call_id=target_msg.tool_call_id,
                id=target_msg.id,
                **kwargs
            )
        elif isinstance(target_msg, AIMessage):
            return AIMessage(
                id=target_msg.id,
                tool_calls=getattr(target_msg, "tool_calls", None) or [],
                **kwargs
            )
        else:
            target_msg.content = new_content
            target_msg.additional_kwargs = kwargs["additional_kwargs"]
            return target_msg
    

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

            result = tools_by_name["compress_paragraph"].invoke(args)
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
                # 显示时转换回agent索引
                agent_range = f"{agent_start_idx}-{agent_end_idx}"
                display_desc = f"段落压缩：{agent_range}替换为总结"
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
            agent_start_idx = self._convert_state_index_to_agent(start_idx)
            agent_end_idx = self._convert_state_index_to_agent(end_idx)
            return [], f"段落压缩失败：范围{agent_start_idx}-{agent_end_idx}内没有找到工具相关消息（AIMessage+tool_calls或ToolMessage）"

        # 第一个工具相关消息必须是 AIMessage+tool_calls
        first_idx, first_msg, first_is_tool_call = tool_related_msgs[0]
        if not first_is_tool_call:
            agent_first_idx = self._convert_state_index_to_agent(first_idx)
            return [], f"段落压缩失败：范围内第一个工具相关消息索引{agent_first_idx}必须是AIMessage且有tool_calls"

        # 最后一个工具相关消息必须是 ToolMessage
        last_idx, last_msg, last_is_tool_call = tool_related_msgs[-1]
        if last_is_tool_call:
            agent_last_idx = self._convert_state_index_to_agent(last_idx)
            return [], f"段落压缩失败：范围内最后一个工具相关消息{agent_last_idx}必须是ToolMessage"

        try:
            # 使用 start_idx 消息的ID创建总结消息
            first_msg = messages[start_idx]
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
            updates.append(summary_msg)

            # 删除其余消息
            for idx in range(start_idx + 1, end_idx + 1):
                target_msg = messages[idx]
                updates.append(RemoveMessage(id=target_msg.id))

            agent_start_idx = self._convert_state_index_to_agent(start_idx)
            agent_end_idx = self._convert_state_index_to_agent(end_idx)

            self.logger.info(f"段落压缩：state索引{agent_start_idx}-{agent_end_idx}已替换为总结")
            return updates, f"段落压缩：{agent_start_idx}-{agent_end_idx}替换为总结"

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

            # 【已移除】token上限检查已移动到model_node.py中统一处理
            # 现在工具执行后不再检查token，而是在发送给模型前统一检查

            content_tokens = estimate_tokens(str(content))
            tool_results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
            self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})

        except Exception as e:
            content = f"工具 {tool_name} 执行出错: {e}"
            tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
            self.logger.error(content, extra={'tag': 'TOOL_FAILURE'})

        return {"tool_results": tool_results, "message_updates": message_updates}

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
