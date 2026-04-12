# utils/message_processor.py
"""
消息处理器：统一处理消息验证、修复、压缩和截断
"""
import logging
import json
from typing import List, Tuple, Any
from collections import deque
from langchain.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from config.configuration import config
from utils.token_utils import estimate_tokens, estimate_messages_tokens, get_tools_token_count


def validate_and_fix_messages(messages: list, logger: logging.Logger = None) -> list:
    """
    验证并修复消息完整性（队列方式）：
    顺序弹出消息，确保 AIMessage(tool_calls) 后紧跟对应 ToolMessage

    逻辑：
    - 弹出消息，如果是 AIMessage 且有 tool_calls：
        - 检查队列头部是否是对应的 ToolMessage
        - 如果是，一起弹出加入结果
        - 如果不是，清空 tool_calls 后加入结果（队列头部消息重新压回）
    - 如果是 ToolMessage 单独出现：丢弃（孤立）
    - 其他消息：直接加入结果
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    input_q = deque(messages)
    output = []
    removed_count = 0
    fixed_count = 0

    while input_q:
        msg = input_q.popleft()

        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                output.append(msg)
                continue

            # 有 tool_calls，需要检查后面是否紧跟对应 ToolMessage
            expected_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
            matched_tools = []

            # 尝试从队列头部取出匹配的 ToolMessage
            while input_q and isinstance(input_q[0], ToolMessage) and len(matched_tools) < len(tool_calls):
                tool_msg = input_q.popleft()
                tc_id = getattr(tool_msg, "tool_call_id", None)

                if tc_id in expected_ids:
                    matched_tools.append(tool_msg)
                    expected_ids.remove(tc_id)
                else:
                    # ID 不匹配，丢弃这个 ToolMessage
                    logger.warning(f"Remove orphaned ToolMessage (tool_call_id={tc_id})",
                                  extra={"tag": "MSG_FIX"})
                    removed_count += 1

            if len(matched_tools) == len(tool_calls):
                # 全部匹配，保留
                output.append(msg)
                output.extend(matched_tools)
            else:
                # 未全部匹配（遇到非 ToolMessage 或数量不足）
                # 将已取出的 ToolMessage 压回队列头部（它们可能是别的 AIMessage 的）
                for tool_msg in reversed(matched_tools):
                    input_q.appendleft(tool_msg)

                logger.warning(f"Fix AIMessage: clearing {len(tool_calls)} out-of-order tool_calls",
                              extra={"tag": "MSG_FIX"})
                fixed_count += 1
                output.append(AIMessage(
                    content=msg.content,
                    id=msg.id,
                    tool_calls=[],
                    additional_kwargs={
                        **getattr(msg, "additional_kwargs", {}),
                        "tool_calls_fixed": True,
                        "original_tool_calls_count": len(tool_calls)
                    }
                ))

        elif isinstance(msg, ToolMessage):
            # 孤立的 ToolMessage（没有前置 AIMessage 匹配）
            tc_id = getattr(msg, "tool_call_id", None)
            logger.warning(f"Remove orphaned ToolMessage (tool_call_id={tc_id})",
                          extra={"tag": "MSG_FIX"})
            removed_count += 1
            # 丢弃，不加入输出

        else:
            # 普通消息
            output.append(msg)

    if removed_count > 0 or fixed_count > 0:
        logger.info(
            f"Message validation: removed {removed_count} orphaned ToolMessages, "
            f"fixed {fixed_count} AIMessages",
            extra={"tag": "MSG_VALIDATED"}
        )

    return output


def _remove_last_message_smart(messages: list, logger: logging.Logger) -> Tuple[list, int, str]:
    """
    智能移除最后一条/一对消息以降低 token

    处理三种场景：
    1. 最后一条是 AIMessage 且有 tool_calls（无结果的工具调用）-> 单条移除
    2. 最后一条是 ToolMessage（有成对的工具调用）-> 和前一条一起移除
    3. 最后一条是普通消息 -> 单条移除

    Returns:
        (移除后的消息列表, 移除的消息数, 移除描述)
    """
    if len(messages) < 1:
        return messages, 0, ""

    result = list(messages)
    last_msg = result[-1]

    # 场景1: 最后一条是 AIMessage 且有 tool_calls（未完成的工具调用）
    if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
        tool_name = last_msg.tool_calls[0].get("name", "unknown") if last_msg.tool_calls else "unknown"
        result = result[:-1]
        desc = f"未完成的工具调用({tool_name})"
        logger.warning(f"Token截断: 移除{desc}", extra={"tag": "TOKEN_TRUNCATE"})
        return result, 1, desc

    # 场景2: 最后一条是 ToolMessage（有成对的工具调用）
    if isinstance(last_msg, ToolMessage) and len(result) >= 2:
        second_last = result[-2]
        if isinstance(second_last, AIMessage) and getattr(second_last, "tool_calls", None):
            # 验证是否匹配
            tool_call_ids = {tc.get("id") for tc in second_last.tool_calls if tc.get("id")}
            if last_msg.tool_call_id in tool_call_ids:
                tool_name = second_last.tool_calls[0].get("name", "unknown") if second_last.tool_calls else "unknown"
                result = result[:-2]  # 移除一对
                desc = f"工具调用对({tool_name})"
                logger.warning(f"Token截断: 移除{desc}", extra={"tag": "TOKEN_TRUNCATE"})
                return result, 2, desc

    # 场景3: 普通消息（HumanMessage 或普通 AIMessage）
    result = result[:-1]
    msg_type = type(last_msg).__name__.replace("Message", "")
    content_preview = str(getattr(last_msg, "content", ""))[:30] + "..."
    desc = f"{msg_type}消息({content_preview})"
    logger.warning(f"Token截断: 移除{desc}", extra={"tag": "TOKEN_TRUNCATE"})
    return result, 1, desc


def truncate_messages_for_token_limit(
    messages: list,
    logger: logging.Logger = None
) -> Tuple[list, bool, int, List[str]]:
    """
    检查消息 token，如果超过截断阈值，智能移除消息直到满足要求

    截断阈值：
    - 从 config.yaml 读取 model.truncate_threshold（比例，如 0.9）
    - 默认 0.9（使用超过 90% 时截断）

    Args:
        messages: 消息列表
        logger: 可选的日志记录器

    Returns:
        (处理后的消息列表, 是否被截断, 移除的总消息数, 移除项目描述列表)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    context_limit = config.get("model.context_limit", 128000)

    # 截断阈值：默认 0.9（使用超过 90% 时截断）
    truncate_threshold = config.get("model.truncate_threshold", 0.9)

    # 预留工具定义占用的 token（在 agent 初始化时计算）
    tools_token_buffer = get_tools_token_count()
    if tools_token_buffer == 0:
        # 如果未设置，使用配置默认值
        tools_token_buffer = config.get("model.tools_token_buffer", 5000)

    safe_threshold = int(context_limit * truncate_threshold) - tools_token_buffer

    current_tokens = estimate_messages_tokens(messages)

    logger.debug(
        f"Token计算: 消息={current_tokens}, 工具={tools_token_buffer}, "
        f"总计~{current_tokens + tools_token_buffer}, 限制={context_limit}, 安全阈值={safe_threshold}",
        extra={"tag": "TOKEN_CALC"}
    )

    if current_tokens <= safe_threshold:
        return messages, False, 0, []

    logger.warning(
        f"Token检查: 消息{current_tokens} + 工具{tools_token_buffer} = {current_tokens + tools_token_buffer}, "
        f"超过安全阈值{safe_threshold}({truncate_threshold*100:.0f}%)，开始截断",
        extra={"tag": "TOKEN_CHECK_TRUNCATE"}
    )

    # 循环移除，直到 token 足够或无法继续
    result_messages = list(messages)
    total_removed = 0
    removed_items = []

    while len(result_messages) > 1:  # 至少保留 SystemMessage + 1条
        # 每次移除后重新计算 token
        result_messages, removed_count, removed_desc = _remove_last_message_smart(
            result_messages, logger
        )

        if removed_count == 0:
            break

        total_removed += removed_count
        removed_items.append(removed_desc)

        # 检查是否已满足要求
        new_tokens = estimate_messages_tokens(result_messages)
        if new_tokens <= safe_threshold:
            break

    if total_removed > 0:
        final_tokens = estimate_messages_tokens(result_messages)
        logger.warning(
            f"Token截断完成: 移除{total_removed}条消息({len(removed_items)}项)，"
            f"token从{current_tokens}降至{final_tokens}",
            extra={"tag": "TOKEN_TRUNCATED"}
        )

    return result_messages, total_removed > 0, total_removed, removed_items


def _count_historical_tool_calls(messages: list) -> int:
    """计算历史消息中的工具调用次数"""
    count = 0
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            count += len(msg.tool_calls)
    return count


def _get_large_messages_list(messages: list) -> list:
    """获取最大的5条消息列表"""
    all_msgs = []
    for i, msg in enumerate(messages):
        if i <= 1:  # 跳过 SystemMessage(0) 和用户初始消息(1)
            continue
        try:
            from langchain_core.messages import message_to_dict
            msg_dict = message_to_dict(msg)
            msg_str = json.dumps(msg_dict, ensure_ascii=False)
            token_count = estimate_tokens(msg_str)
        except Exception:
            content = str(getattr(msg, 'content', '') or '')
            token_count = estimate_tokens(content)
        msg_type = type(msg).__name__.replace("Message", "")
        preview = str(getattr(msg, 'content', ''))[:30].replace('\n', ' ')
        if len(str(getattr(msg, 'content', '') or '')) > 30:
            preview += "..."
        all_msgs.append((i, msg_type, token_count, preview))
    all_msgs.sort(key=lambda x: x[2], reverse=True)
    return all_msgs[:5]



def generate_compress_prompts(messages: list, logger: logging.Logger = None) -> list:
    """
    生成压缩提示消息（统一处理所有预防性提示）

    优先级：
    1. Token 告警提示（使用超过告警阈值）
    2. 消息数量提示（>=100条）
    3. 每5次调用提示（调用次数 % 5 == 0）
    4. 大结果提示（最后一条 ToolMessage > 1000 token）

    Returns:
        需要添加的提示消息列表
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    prompts = []

    # 检查是否已有同类提示（避免重复）
    def has_prompt(prefix: str) -> bool:
        return any(
            isinstance(msg, HumanMessage) and msg.content.startswith(prefix)
            for msg in messages
        )

    # 0. Token 告警检查（最高优先级）
    context_limit = config.get("model.context_limit", 128000)
    warn_threshold = config.get("model.warn_threshold", 0.8)  # 默认 80% 告警
    current_tokens = estimate_messages_tokens(messages)
    usage_ratio = current_tokens / context_limit

    if usage_ratio >= warn_threshold and not has_prompt("【系统提示】上下文Token使用率"):
        # 获取大消息列表（超过 context_limit 10% 的消息）
        large_msgs = _get_large_messages_list(messages, context_limit, threshold_ratio=0.1)

        # 构建提示内容
        prompt_content = (
            f"【系统提示】上下文Token使用率已达 {usage_ratio*100:.0f}%（阈值 {warn_threshold*100:.0f}%），"
            f"当前 {current_tokens}/{context_limit}。"
            f"请立即调用压缩工具压缩上下文后再继续。"
        )

        # 如果有大消息，添加参考列表
        if large_msgs:
            prompt_content += "\n\n【建议优先压缩以下大消息】"
            for idx, msg_type, tokens, preview in large_msgs[:10]:  # 最多显示10条
                prompt_content += f"\n- 索引{idx} ({msg_type}): ~{tokens} tokens | {preview}"
            if len(large_msgs) > 10:
                prompt_content += f"\n... 还有 {len(large_msgs) - 10} 条大消息"
            prompt_content += "\n\n你可以使用单条压缩工具或段落压缩工具来减少上下文。"

        prompts.append(HumanMessage(content=prompt_content))
        logger.info(f"触发Token告警提示({usage_ratio*100:.1f}%), 发现{len(large_msgs)}条大消息", extra={"tag": "TOKEN_WARN"})
        return prompts  # 最高优先级，直接返回

    # 1. 消息数量检查（次高优先级）
    msg_count = len(messages)
    if msg_count >= 100 and not has_prompt("【系统提示】当前对话消息数"):
        prompts.append(HumanMessage(
            content=f"【系统提示】当前对话消息数已达{msg_count}条，已超过100条。"
                    f"请立即调用压缩工具压缩上下文后再继续。"
        ))
        logger.info(f"触发消息数量压缩提示({msg_count}条消息)", extra={"tag": "COMPRESS_MSG_COUNT"})
        return prompts  # 优先返回，避免信息过载

    # 2. 每5次调用检查
    historical_calls = _count_historical_tool_calls(messages)
    if historical_calls >= 10 and historical_calls % 5 == 0 and not has_prompt("【系统提示】已进行"):
        prompts.append(HumanMessage(
            content=f"【系统提示】已进行{historical_calls}次工具调用，建议执行一次上下文压缩以保持对话效率"
        ))
        logger.info(f"触发压缩建议提示(累计{historical_calls}次工具调用)", extra={"tag": "COMPRESS_PROMPT"})
        return prompts  # 避免同时触发多个提示

    # 3. 大结果检查（最后一条是 ToolMessage 且内容较大，且总token>20000时才频繁提醒）
    if messages and isinstance(messages[-1], ToolMessage):
        last_content = messages[-1].content
        content_tokens = estimate_tokens(str(last_content))
        total_tokens = estimate_messages_tokens(messages)

        # 大结果提示：>5000 token、总token>20000、且历史调用次数 > 5
        if (content_tokens > 5000 and
            total_tokens > 20000 and
            historical_calls > 5 and
            not has_prompt("【系统提示】上一个工具调用")):
            prompts.append(HumanMessage(
                content=f"【系统提示】上一个工具调用产生了较大的结果（约{content_tokens} token）。"
                        f"建议压缩其他历史消息或对该结果进行摘要/清空，以节省上下文空间。"
            ))
            logger.info(f"大结果提示: 返回{content_tokens}token, 总token={total_tokens}", extra={"tag": "LARGE_RESULT_PROMPT"})

    return prompts


def process_messages_before_send(
    messages: list,
    logger: logging.Logger = None,
    validate: bool = True,
    truncate: bool = True,
    generate_prompts: bool = True
) -> Tuple[list, dict]:
    """
    发送给模型前的统一消息处理入口

    处理流程：
    1. Token 截断（如果需要）
    2. 验证并修复消息完整性（修复截断造成的工具调用链断裂）
    3. 生成压缩提示

    Args:
        messages: 原始消息列表
        logger: 可选的日志记录器
        validate: 是否执行验证修复
        truncate: 是否执行 token 截断
        generate_prompts: 是否生成压缩提示

    Returns:
        (处理后的消息列表, 处理信息字典)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    result = list(messages)
    info = {
        "validated": False,
        "truncated": False,
        "removed_count": 0,
        "removed_items": [],
        "prompts_added": 0,
        "original_token": 0,
        "final_token": 0
    }

    # 记录原始 token（截断前）
    info["original_token"] = estimate_messages_tokens(result)
    logger.info(f"process_messages_before_send 处理前: {info['original_token']} tokens, {len(result)} 条消息",
                extra={'tag': 'MSG_PROCESS_START'})

    # 1. Token 截断（先执行，可能破坏工具调用链）
    if truncate:
        result, was_truncated, removed_count, removed_items = truncate_messages_for_token_limit(
            result, logger
        )
        info["truncated"] = was_truncated
        info["removed_count"] = removed_count
        info["removed_items"] = removed_items

    # 2. 验证修复（修复截断造成的工具调用链断裂）
    if validate:
        result = validate_and_fix_messages(result, logger)
        info["validated"] = True

    # 3. 生成压缩提示
    if generate_prompts:
        prompts = generate_compress_prompts(result, logger)
        if prompts:
            result.extend(prompts)
            info["prompts_added"] = len(prompts)

    info["final_token"] = estimate_messages_tokens(result)
    logger.info(f"process_messages_before_send 处理后: {info['final_token']} tokens (截断={info['truncated']}, 验证={info['validated']}, 提示={info['prompts_added']})",
                extra={'tag': 'MSG_PROCESS_END'})

    return result, info
