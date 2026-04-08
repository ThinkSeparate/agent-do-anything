# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage
from langchain_core.messages import BaseMessage, AIMessage
from core.common.state_define import AgentState
from tools import tools_by_name
from typing import List, Tuple
from config.configuration import config


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


def create_tool_node(max_consecutive_failures: int = 3):
    """
    创建工具执行节点，包含压缩功能。
    """
    logger = logging.getLogger(__name__)

    def execute_real_compression(messages: List[BaseMessage], operations: List[dict]) -> Tuple[List[BaseMessage], str]:
        """
        实际执行压缩操作的函数

        规则：
        1. 不删除任何消息，只替换内容
        2. delete = 清空内容为占位符
        3. summarize = 替换为摘要字符串
        4. 保留所有消息结构（包括 tool_calls）

        Args:
            messages: 当前消息列表
            operations: 压缩操作策略

        Returns:
            (消息更新列表, 摘要描述字符串)
        """
        updates = []

        # 验证和收集有效操作
        valid_operations: List[Tuple[int, int, str, dict]] = []  # (op_idx, msg_idx, op_type, op)
        for i, op in enumerate(operations):
            msg_idx = op.get("message_index")
            op_type = op.get("operation")

            if not isinstance(msg_idx, int):
                logger.warning(f"压缩操作{i}：索引{msg_idx}不是整数，跳过")
                continue

            # 禁止修改系统消息(0)和用户消息(1)
            if msg_idx == 0:
                logger.error(f"压缩操作{i}：禁止修改系统消息(索引0)")
                continue
            if msg_idx == 1:
                logger.error(f"压缩操作{i}：禁止修改用户消息(索引1)")
                continue

            if not (0 <= msg_idx < len(messages)):
                logger.warning(f"压缩操作{i}：索引{msg_idx}越界（范围：0-{len(messages)-1}），跳过")
                continue

            valid_operations.append((i, msg_idx, op_type, op))

        # 构建摘要描述
        compressed_indices = [msg_idx for (_, msg_idx, _, _) in valid_operations]
        summary_desc = f"（摘要描述：对第{compressed_indices}条消息进行了压缩处理）" if compressed_indices else "（无有效压缩操作）"

        # 按索引从大到小处理
        valid_operations.sort(key=lambda x: x[1], reverse=True)

        for op_idx, msg_idx, op_type, op in valid_operations:
            target_msg = messages[msg_idx - 1]

            try:
                # 获取新内容
                if op_type == "summarize":
                    summary = op.get("summary_text", "").strip()
                    new_content = summary if summary else "[摘要]"
                else:  # delete
                    new_content = ""

                # 根据消息类型创建新消息
                if isinstance(target_msg, ToolMessage):
                    new_msg = ToolMessage(
                        content=new_content,
                        tool_call_id=target_msg.tool_call_id,
                        id=target_msg.id,
                        additional_kwargs={
                            **getattr(target_msg, "additional_kwargs", {}),
                            "original_index": msg_idx,
                            "compressed": True
                        }
                    )
                    logger.info(f"压缩操作{op_idx}：索引{msg_idx} ToolMessage {'摘要' if op_type == 'summarize' else '清空'}")

                elif isinstance(target_msg, AIMessage):
                    new_msg = AIMessage(
                        content=new_content,
                        id=target_msg.id,
                        tool_calls=getattr(target_msg, "tool_calls", None),
                        additional_kwargs={
                            **getattr(target_msg, "additional_kwargs", {}),
                            "original_index": msg_idx,
                            "compressed": True
                        }
                    )
                    logger.info(f"压缩操作{op_idx}：索引{msg_idx} AIMessage {'摘要' if op_type == 'summarize' else '清空'}")

                else:
                    # 其他类型（HumanMessage等）- 直接替换内容
                    target_msg.content = new_content
                    target_msg.additional_kwargs = {
                        **getattr(target_msg, "additional_kwargs", {}),
                        "original_index": msg_idx,
                        "compressed": True
                    }
                    new_msg = target_msg
                    logger.info(f"压缩操作{op_idx}：索引{msg_idx} {type(target_msg).__name__} {'摘要' if op_type == 'summarize' else '清空'}")

                updates.append(new_msg)

            except Exception as e:
                logger.error(f"压缩操作{op_idx}执行失败: {e}")

        return updates, summary_desc

    def tool_node(state: AgentState) -> dict:
        """执行工具调用，包含压缩处理"""
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

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})

            if tool_name == "compress_messages":
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
                        content = "压缩工具返回空操作列表"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.warning(content, extra={'tag': 'COMPRESS_EMPTY'})
                        continue

                    compression_updates, summary_desc = execute_real_compression(messages, operations)

                    if compression_updates:
                        message_updates.extend(compression_updates)
                        logger.info(f"成功压缩 {len(compression_updates)} 条消息", extra={'tag': 'COMPRESS_SUCCESS'})
                    else:
                        logger.warning("压缩操作未产生更新", extra={'tag': 'COMPRESS_NO_UPDATE'})

                    tool_results.append(ToolMessage(
                        content=summary_desc,
                        tool_call_id=tool_call["id"]
                    ))

                except Exception as e:
                    content = f"压缩处理出错: {e}"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'COMPRESS_FAILURE'})

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
                    except Exception as e:
                        content = f"工具 {tool_name} 执行出错: {e}"
                        consecutive_failures += 1
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.error(content, extra={'tag': 'TOOL_FAILURE'})

        # 计算历史消息中的工具调用次数
        historical_tool_calls = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                historical_tool_calls += len(msg.tool_calls)

        # 每5次工具调用后，添加压缩提示（通过HumanMessage追加，不修改原用户消息）
        compress_prompt_msg = None
        if historical_tool_calls % 5 == 0 and historical_tool_calls > 0:
            # 检查是否已经有压缩提示在消息列表中，避免重复添加
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

        return {"messages": all_results, "consecutive_failures": consecutive_failures}

    return tool_node
