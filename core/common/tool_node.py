# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage, RemoveMessage
from langchain_core.messages import BaseMessage, AIMessage, message_to_dict
from core.common.state_define import AgentState
from typing import List, Tuple
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


def create_tool_node(max_consecutive_failures: int = 3,
                     session_id: int = None,
                     project_directory: str = None):
    """
    创建工具执行节点，包含压缩功能和状态持久化。
    """
    logger = logging.getLogger(__name__)
    persistence = SessionPersistence(project_directory) if project_directory else None

    def execute_single_compression(messages: List[BaseMessage], operations: List[dict]) -> Tuple[List[BaseMessage], str]:
        """
        执行单条消息压缩。

        规则：
        1. 不删除任何消息，只替换内容
        2. clear = 清空内容
        3. summarize = 替换为摘要字符串
        4. 保留所有消息结构（包括 tool_calls）
        """
        updates = []
        valid_operations = []

        # 验证操作
        for i, op in enumerate(operations):
            display_idx = op.get("message_index")
            op_type = op.get("operation")

            if not isinstance(display_idx, int):
                continue
            # 禁止修改系统消息(0)和用户消息(1)
            if display_idx == 0 or display_idx == 1:
                logger.error(f"压缩操作{i}：禁止修改系统消息(0)或用户消息(1)")
                continue
            if not (0 <= display_idx < len(messages)):
                logger.warning(f"压缩操作{i}：索引{display_idx}越界，跳过")
                continue
            if op_type not in ["clear", "summarize"]:
                continue
            if op_type == "summarize" and not op.get("summary_text", "").strip():
                continue

            valid_operations.append((i, display_idx, op_type, op))

        # 按索引从大到小处理
        valid_operations.sort(key=lambda x: x[1], reverse=True)
        compressed_indices = []

        for op_idx, display_idx, op_type, op in valid_operations:
            target_msg = messages[display_idx]

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
                            "original_index": display_idx,
                            "compressed": True
                        }
                    )
                    updates.append(new_msg)
                    logger.info(f"单条压缩{op_idx}：索引{display_idx} ToolMessage {'摘要' if op_type == 'summarize' else '清空'}")

                elif isinstance(target_msg, AIMessage):
                    new_msg = AIMessage(
                        content=new_content,
                        id=target_msg.id,
                        tool_calls=getattr(target_msg, "tool_calls", None),
                        additional_kwargs={
                            **getattr(target_msg, "additional_kwargs", {}),
                            "original_index": display_idx,
                            "compressed": True
                        }
                    )
                    updates.append(new_msg)
                    logger.info(f"单条压缩{op_idx}：索引{display_idx} AIMessage {'摘要' if op_type == 'summarize' else '清空'}")

                else:
                    target_msg.content = new_content
                    target_msg.additional_kwargs = {
                        **getattr(target_msg, "additional_kwargs", {}),
                        "original_index": display_idx,
                        "compressed": True
                    }
                    updates.append(target_msg)
                    logger.info(f"单条压缩{op_idx}：索引{display_idx} {type(target_msg).__name__} {'摘要' if op_type == 'summarize' else '清空'}")

                compressed_indices.append(display_idx)

            except Exception as e:
                logger.error(f"单条压缩操作{op_idx}执行失败: {e}")

        summary_desc = f"单条压缩：{compressed_indices}" if compressed_indices else "（无有效单条压缩操作）"
        return updates, summary_desc

    def execute_paragraph_compression(messages: List[BaseMessage], start_idx: int, end_idx: int, summary_text: str) -> Tuple[List[BaseMessage], str]:
        """
        执行段落压缩。将一段连续消息整体总结替换。

        规则：
        1. 必须成对：start_idx必须是AIMessage(tool_calls)，end_idx必须是ToolMessage
        2. 中间消息必须交替：AIMessage(tool_calls) -> ToolMessage -> AIMessage(tool_calls) -> ToolMessage
        3. 将范围内所有消息清空，在start_idx位置插入总结
        4. 禁止包含系统消息(0)或用户消息(1)
        """
        updates = []

        # 验证参数
        if not isinstance(start_idx, int) or not isinstance(end_idx, int):
            return [], "段落压缩失败：start_index和end_index必须是整数"
        if not summary_text or not summary_text.strip():
            return [], "段落压缩失败：summary不能为空"
        # 禁止跨越系统消息(0)或用户消息(1)
        if start_idx <= 1 or end_idx <= 1:
            logger.error(f"段落压缩：禁止包含系统消息(0)或用户消息(1)")
            return [], "段落压缩失败：禁止包含索引0或1"
        if not (0 <= start_idx < len(messages) and 0 <= end_idx < len(messages)):
            logger.warning(f"段落压缩：索引越界")
            return [], "段落压缩失败：索引越界"
        if start_idx >= end_idx:
            return [], "段落压缩失败：start_index必须小于end_index"

        # 验证成对约束：找出范围内所有工具相关消息（AIMessage+tool_calls 或 ToolMessage）
        tool_related_msgs = []
        for idx in range(start_idx, end_idx + 1):
            msg = messages[idx]
            is_tool_call = isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
            is_tool_result = isinstance(msg, ToolMessage)
            if is_tool_call or is_tool_result:
                tool_related_msgs.append((idx, msg, is_tool_call))

        # 第一个工具相关消息必须是 AIMessage+tool_calls
        if tool_related_msgs:
            first_idx, first_msg, first_is_tool_call = tool_related_msgs[0]
            if not first_is_tool_call:
                return [], f"段落压缩失败：范围内第一个工具相关消息（索引{first_idx}）必须是AIMessage且有tool_calls"

            # 最后一个工具相关消息必须是 ToolMessage
            last_idx, last_msg, last_is_tool_call = tool_related_msgs[-1]
            if last_is_tool_call:
                return [], f"段落压缩失败：范围内最后一个工具相关消息（索引{last_idx}）必须是ToolMessage"

        try:
            # 1. 使用 start_idx 消息的ID创建总结消息（add_messages会替换原消息）
            first_msg = messages[start_idx]
            # 段落压缩会删除范围内的所有工具调用消息对
            # 新的总结消息不包含tool_calls，因为它代表已完成的整个段落
            summary_msg = AIMessage(
                content=f"[段落总结] {summary_text}",
                id=first_msg.id,  # 使用原ID实现替换
                tool_calls=None,  # 总结消息不包含tool_calls
                additional_kwargs={
                    **getattr(first_msg, "additional_kwargs", {}),
                    "compressed": True,
                    "is_paragraph_summary": True,
                    "original_range": f"{start_idx}-{end_idx}"
                }
            )
            updates.append(summary_msg)

            # 2. 删除其余消息（使用 RemoveMessage）
            for idx in range(start_idx + 1, end_idx + 1):
                target_msg = messages[idx]
                updates.append(RemoveMessage(id=target_msg.id))

            logger.info(f"段落压缩：索引{start_idx}-{end_idx}已替换为总结")
            return updates, f"段落压缩：{start_idx}-{end_idx}替换为总结"

        except Exception as e:
            logger.error(f"段落压缩执行失败: {e}")
            return [], f"段落压缩失败: {e}"

    def tool_node(state: AgentState) -> dict:
        """执行工具调用，包含压缩处理"""
        # 延迟导入避免循环导入
        from tools import tools_by_name

        messages = state["messages"]
        tool_calls = state["messages"][-1].tool_calls
        consecutive_failures = state.get("consecutive_failures", 0)

        # 获取token限制配置
        context_limit = config.get('model.context_limit', 128000)
        # 预留余量给系统提示和模型回复
        safe_threshold = context_limit - 8000

        tool_results = []
        message_updates = []

        # 计算当前消息的token数
        current_tokens = estimate_messages_tokens(messages)
        logger.debug(f"当前消息token估算: {current_tokens}, 安全阈值: {safe_threshold}", extra={'tag': 'TOKEN_CHECK'})

        # 计算历史消息中的工具调用次数（提前计算，供后续使用）
        historical_tool_calls = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                historical_tool_calls += len(msg.tool_calls)

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})

            if tool_name in ["compress_message", "compress_messages"]:
                try:
                    tool = tools_by_name.get(tool_name)
                    if tool is None:
                        content = f"工具 '{tool_name}' 不存在"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        consecutive_failures += 1
                        continue

                    result = tool.invoke(args)
                    operations = result.get("operations", []) if isinstance(result, dict) else []

                    if not operations:
                        content = "单条压缩工具返回空操作列表"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.warning(content, extra={'tag': 'COMPRESS_EMPTY'})
                        continue

                    compression_updates, summary_desc = execute_single_compression(messages, operations)

                    if compression_updates:
                        message_updates.extend(compression_updates)
                        logger.info(f"成功单条压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_SUCCESS'})
                    else:
                        logger.warning("单条压缩操作未产生更新", extra={'tag': 'COMPRESS_NO_UPDATE'})

                    tool_results.append(ToolMessage(
                        content=summary_desc,
                        tool_call_id=tool_call["id"]
                    ))

                except Exception as e:
                    content = f"单条压缩处理出错: {e}"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'COMPRESS_FAILURE'})

            elif tool_name == "compress_paragraph":
                try:
                    # 段落压缩限制：消息数必须超过80条才允许使用
                    if len(messages) < 80:
                        content = f"段落压缩拒绝：当前消息数 {len(messages)} 条，未达到 80 条的最低要求。请先使用 compress_message 进行单条压缩。"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.warning(f"段落压缩被拒绝：消息数{len(messages)}<80", extra={'tag': 'COMPRESS_PARAGRAPH_DENIED'})
                        continue

                    tool = tools_by_name.get(tool_name)
                    if tool is None:
                        content = f"工具 '{tool_name}' 不存在"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        consecutive_failures += 1
                        continue

                    result = tool.invoke(args)
                    if not isinstance(result, dict) or not result.get("valid"):
                        content = result.get("message", "段落压缩参数无效") if isinstance(result, dict) else "段落压缩返回无效结果"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.warning(content, extra={'tag': 'COMPRESS_PARAGRAPH_INVALID'})
                        continue

                    compression_updates, summary_desc = execute_paragraph_compression(
                        messages,
                        result.get("start_index"),
                        result.get("end_index"),
                        result.get("summary")
                    )

                    if compression_updates:
                        message_updates.extend(compression_updates)
                        logger.info(f"成功段落压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_PARAGRAPH_SUCCESS'})
                    else:
                        logger.warning("段落压缩操作未产生更新", extra={'tag': 'COMPRESS_PARAGRAPH_NO_UPDATE'})

                    tool_results.append(ToolMessage(
                        content=summary_desc,
                        tool_call_id=tool_call["id"]
                    ))

                except Exception as e:
                    content = f"段落压缩处理出错: {e}"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'COMPRESS_PARAGRAPH_FAILURE'})

            else:
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    content = f"工具 '{tool_name}' 不存在"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'TOOL_ERROR'})
                else:
                    try:
                        content = tool.invoke(args)
                        consecutive_failures = 0

                        # 检查添加此工具结果后是否会超过token上限
                        content_tokens = estimate_tokens(str(content))
                        projected_tokens = current_tokens + content_tokens

                        if projected_tokens > safe_threshold:
                            # 超过阈值，返回提示模型压缩的消息
                            overflow = projected_tokens - context_limit
                            warning_content = "【系统提示】当前上下文已接近Token上限，请立即调用compress_messages压缩上下文后再继续。"
                            tool_results.append(ToolMessage(content=warning_content, tool_call_id=tool_call["id"]))
                            logger.warning(f"触发Token上限提示: {projected_tokens}>{safe_threshold}", extra={'tag': 'TOKEN_PROMPT'})
                        else:
                            tool_results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
                            logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})

                            # 检查结果大小，如果超过1000 token且已有5次以上工具调用，提示可以压缩
                            if content_tokens > 1000 and historical_tool_calls > 5:
                                large_result_prompt = (
                                    f"【系统提示】上一个工具调用产生了较大的结果（约{content_tokens} token）。"
                                    f"如果你只需要该结果的部分内容（<30%的连续片段），"
                                    f"请使用单条压缩工具对该结果进行摘要或清空。"
                                )
                                # 使用 HumanMessage 而不是 ToolMessage，因为这不是工具调用的响应
                                tool_results.append(HumanMessage(content=large_result_prompt))
                                logger.info(f"大结果提示: 工具{tool_name}返回{content_tokens}token", extra={'tag': 'LARGE_RESULT_PROMPT'})
                    except Exception as e:
                        content = f"工具 {tool_name} 执行出错: {e}"
                        consecutive_failures += 1
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.error(content, extra={'tag': 'TOOL_FAILURE'})

        # 压缩提示优先级管理（从高到低）：
        # 1. Token上限（已在工具执行时检查）
        # 2. 消息条数>=100
        # 3. 工具调用次数（每5次）
        # 4. 大结果提示（已在工具执行时检查，最低优先级）

        compress_prompt_msg = None
        message_count = len(messages)

        # 优先级2：检查消息数量，超过100条时提示压缩
        if message_count >= 100:
            has_msg_count_prompt = any(
                isinstance(msg, HumanMessage) and msg.content.startswith("【系统提示】当前对话消息数")
                for msg in messages
            )
            if not has_msg_count_prompt:
                compress_prompt_msg = HumanMessage(
                    content=f"【系统提示】当前对话消息数已达{message_count}条，已超过100条。请立即调用压缩工具：\n"
                           f"- 消息数80-100：使用 compress_message 进行单条删除/摘要\n"
                           f"- 消息数>100：可使用 compress_paragraph 进行段落总结（更高效）"
                )
                logger.info(f"触发消息数量压缩提示({message_count}条消息)", extra={'tag': 'COMPRESS_MSG_COUNT'})

        # 优先级3：每5次工具调用后，添加压缩提示（仅当高优先级提示未触发时）
        elif historical_tool_calls % 5 == 0 and historical_tool_calls > 0:
            has_compress_prompt = any(
                isinstance(msg, HumanMessage) and msg.content.startswith("【系统提示】已进行")
                for msg in messages
            )
            if not has_compress_prompt:
                compress_prompt_msg = HumanMessage(
                    content=f"【系统提示】已进行{historical_tool_calls}次工具调用，请评估是否需要压缩上下文"
                )
                logger.info(f"触发压缩评估提示(累计{historical_tool_calls}次工具调用)", extra={'tag': 'COMPRESS_PROMPT'})

        all_results = message_updates + tool_results

        # 添加压缩提示消息（如果有且未重复）
        if compress_prompt_msg:
            all_results.append(compress_prompt_msg)

        if consecutive_failures >= max_consecutive_failures:
            recovery_prompt = (
                f"注意：已连续失败 {consecutive_failures} 次。\n"
                f"请分析失败原因，尝试不同策略。"
            )
            all_results.append(HumanMessage(content=recovery_prompt))
            logger.warning("已注入恢复提示", extra={'tag': 'STRATEGY_SHIFT'})
            consecutive_failures = 0

        # 保存会话状态（如果启用了持久化）
        if persistence and session_id:
            try:
                # 合并消息：原始消息 + 新结果
                all_messages = messages + all_results
                state_to_save = {
                    "messages": [message_to_dict(m) for m in all_messages],
                    "consecutive_failures": consecutive_failures
                }
                persistence.save_state(session_id, state_to_save)
                logger.debug(f"会话状态已保存: session_id={session_id}",
                           extra={'tag': 'STATE_SAVED'})
            except Exception as e:
                logger.error(f"保存会话状态失败: {e}",
                           extra={'tag': 'STATE_SAVE_ERROR'})

        return {"messages": all_results, "consecutive_failures": consecutive_failures}

    return tool_node
