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
        all_msgs.append((msg.index, msg_type, token_count, preview))
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
        large_msgs = _get_large_messages_list(messages)

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

    # # 1. 消息数量检查（次高优先级）
    # msg_count = len(messages)
    # if msg_count >= 100 and content_tokens > context_limit * 0.6 and not has_prompt("【系统提示】当前对话消息数"):
    #     prompts.append(HumanMessage(
    #         content=f"【系统提示】当前对话消息数已达{msg_count}条，已超过100条。"
    #                 f"请立即调用压缩工具压缩上下文后再继续。"
    #     ))
    #     logger.info(f"触发消息数量压缩提示({msg_count}条消息)", extra={"tag": "COMPRESS_MSG_COUNT"})
    #     return prompts  # 优先返回，避免信息过载

    # 2. 每10次调用检查
    historical_calls = _count_historical_tool_calls(messages)
    if historical_calls % 10 == 0 and not has_prompt("【系统提示】已进行"):
        prompts.append(HumanMessage(
            content=f"【系统提示】对话已进行{historical_calls}次工具调用，上下文可能持续增长。" 
                f"请注意管理上下文长度，并依据‘效率规则’评估是否有足够多的可压缩内容（如早期步骤、冗长结果），以决定是否执行压缩。"
        ))
        logger.info(f"触发压缩建议提示(累计{historical_calls}次工具调用)", extra={"tag": "COMPRESS_PROMPT"})
        return prompts  # 避免同时触发多个提示

    # 3. 大结果检查（最后一条是 ToolMessage 且内容较大，且总token>20000时才频繁提醒）
    if messages and isinstance(messages[-1], ToolMessage):
        last_content = messages[-1].content
        content_tokens = estimate_tokens(str(last_content))
        total_tokens = estimate_messages_tokens(messages)

        # 大结果提示：>5000 token、总token>20000、且历史调用次数 > 6
        if (content_tokens > 5000 and
            total_tokens > 20000 and
            historical_calls > 10 and
            not has_prompt("【系统提示】上一个工具调用")):
            prompts.append(HumanMessage(
                f"【系统提示】上一个工具调用产生了较大的结果（约{content_tokens} token），导致上下文显著增长。\n" \
                    f"请注意管理上下文长度，并依据压缩规则判断是否需要、以及对哪些历史消息采取压缩操作。"
            ))
            logger.info(f"大结果提示: 返回{content_tokens}token, 总token={total_tokens}", extra={"tag": "LARGE_RESULT_PROMPT"})

    return prompts


def _cleanup_empty_messages(messages: list, logger: logging.Logger = None) -> Tuple[list, int, int, list]:
    """
    清理空消息：检测并丢弃连续空 content 的消息段落

    策略：
    - 遍历消息，连续收集可删除的空内容消息
    - HumanMessage 空内容可删除（系统提示类消息，长期迭代后可清理）
    - 工具调用和返回必须成对删除：遇到空 AIMessage 检查下一条 ToolMessage
      - 如果 ToolMessage 也空，两者都加入可删除列表
      - 如果 ToolMessage 不空，停止当前段落（保护工具链）
    - 达到阈值（默认3条）时，空段落被整体删除

    注意：此功能不是"压缩"，是直接丢弃空消息。如需保留信息的压缩，请使用 compress_messages 工具。

    Returns:
        (清理后的消息列表, 清理的段落数量, 删除的消息数量, 清理信息列表)
        清理信息列表: [(first_msg_idx, last_msg_idx, count), ...] 用于后续生成提示消息
            - first_msg_idx: 段落第一条消息的 index 字段值
            - last_msg_idx: 段落最后一条消息的 index 字段值
            - count: 删除的消息数量
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    EMPTY_THRESHOLD = 3  # 连续空消息阈值

    def _is_empty_content(msg) -> bool:
        """检查消息 content 是否为空"""
        content = str(getattr(msg, 'content', '') or '').strip()
        return len(content) == 0 or content in ['[摘要]', '[段落总结]', '[已压缩]']

    def _can_be_removed(msg) -> bool:
        """检查消息是否可以被删除（SystemMessage 不可删除）"""
        return not isinstance(msg, SystemMessage) and _is_empty_content(msg)

    result = []
    cleanup_count = 0
    removed_count = 0
    cleanup_info_list = []  # 收集清理信息用于后续生成提示
    i = 0

    while i < len(messages):
        msg = messages[i]

        # 尝试收集可删除段落
        if _can_be_removed(msg):
            removable_indices = []  # 可删除消息索引列表
            j = i

            while j < len(messages):
                current_msg = messages[j]

                # SystemMessage 或非空消息中断收集
                if isinstance(current_msg, SystemMessage) or not _is_empty_content(current_msg):
                    break

                # 检查是否是带 tool_calls 的 AIMessage（需要成对处理）
                if isinstance(current_msg, AIMessage) and getattr(current_msg, "tool_calls", None):
                    tool_calls = current_msg.tool_calls
                    expected_id = tool_calls[0].get("id") if tool_calls else None

                    # 检查下一条是否是对应的 ToolMessage
                    if j + 1 < len(messages):
                        next_msg = messages[j + 1]
                        if isinstance(next_msg, ToolMessage) and next_msg.tool_call_id == expected_id:
                            # 下一条是匹配的 ToolMessage，检查是否为空
                            if _is_empty_content(next_msg):
                                # 成对都空，加入可删除列表
                                removable_indices.extend([j, j + 1])
                                j += 2  # 跳过两条
                                continue
                            else:
                                # ToolMessage 非空，停止收集（不能破坏链）
                                break

                    # 没有下一条，或不匹配，或不是 ToolMessage
                    # 这种情况理论上不会出现，但防御性处理：AIMessage 单独可删
                    removable_indices.append(j)
                    j += 1
                elif isinstance(current_msg, ToolMessage):
                    # 孤立的 ToolMessage（前面没有匹配的 AIMessage）
                    # 说明消息序列有问题，不应该删除，中断收集
                    logger.warning(
                        f"空消息清理: 检测到孤立ToolMessage(索引{j})，中断收集",
                        extra={"tag": "CLEANUP_ORPHAN_TOOL"}
                    )
                    break
                else:
                    # HumanMessage，单独可删
                    removable_indices.append(j)
                    j += 1

            # 检查是否达到压缩阈值
            if len(removable_indices) >= EMPTY_THRESHOLD:
                # 获取段落起始和结束消息，使用 msg.index 字段值
                first_msg_pos = removable_indices[0]
                last_msg_pos = removable_indices[-1]
                first_msg = messages[first_msg_pos]
                last_msg = messages[last_msg_pos]

                # 获取消息的 index 字段值（不是列表位置）
                first_msg_idx = getattr(first_msg, 'index', first_msg_pos)
                last_msg_idx = getattr(last_msg, 'index', last_msg_pos)

                # 【修改】不再直接追加提示消息，而是收集清理信息
                # 提示消息将在 process_messages_before_send 最后统一追加
                cleanup_info_list.append((first_msg_idx, last_msg_idx, len(removable_indices)))
                cleanup_count += 1
                removed_count += len(removable_indices)

                logger.info(
                    f"空消息清理: 消息index {first_msg_idx}-{last_msg_idx} 的{len(removable_indices)}条空消息被移除",
                    extra={"tag": "EMPTY_CLEANUP"}
                )

                # 跳过已处理的消息
                i = j
                continue

        # 不可删除，保留原消息
        result.append(msg)
        i += 1

    if cleanup_count > 0:
        logger.info(
            f"空消息清理完成: 清理了{cleanup_count}个段落，删除了{removed_count}条空消息",
            extra={"tag": "EMPTY_CLEANUP_DONE"}
        )

    return result, cleanup_count, removed_count, cleanup_info_list


def _optimize_large_tool_results(messages: list, logger: logging.Logger = None) -> Tuple[list, int, int]:
    """
    优化大工具调用结果：当 ToolMessage 内容很大时，清空对应 AIMessage 的 tool_calls args

    策略：
    - 遍历消息，找到所有 ToolMessage
    - 如果 ToolMessage 的 content 超过阈值（3000 token），视为大结果
    - 找到对应的 AIMessage（通过 tool_call_id 匹配）
    - 清空那个 AIMessage 的 tool_calls 中对应条目的 args，保留 id 和 name

    Returns:
        (优化后的消息列表, 处理的大结果数量, 节省的 token 估算)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    LARGE_RESULT_THRESHOLD = 3000  # 大结果阈值：3000 token

    # 找到所有大结果的 tool_call_id
    large_result_ids = {}  # tool_call_id -> token_count
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content_tokens = estimate_tokens(str(getattr(msg, 'content', '') or ''))
            if content_tokens > LARGE_RESULT_THRESHOLD:
                tc_id = getattr(msg, 'tool_call_id', None)
                if tc_id:
                    large_result_ids[tc_id] = content_tokens

    if not large_result_ids:
        return messages, 0, 0

    # 遍历消息，清空对应 AIMessage 的 tool_calls args
    optimized_count = 0
    saved_tokens = 0
    result = []

    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                # 检查是否有 tool_call 需要优化
                new_tool_calls = []
                modified = False
                for tc in tool_calls:
                    tc_id = tc.get("id")
                    if tc_id in large_result_ids:
                        # 清空 args，保留 id 和 name
                        original_args = tc.get("args", {})
                        args_tokens = estimate_tokens(json.dumps(original_args, ensure_ascii=False))
                        saved_tokens += args_tokens

                        new_tc = {
                            **tc,
                            "args": {"_optimized": True, "_original_tokens": args_tokens}
                        }
                        new_tool_calls.append(new_tc)
                        optimized_count += 1
                        modified = True
                        logger.debug(
                            f"优化大结果: tool_call_id={tc_id}, "
                            f"tool={tc.get('name', 'unknown')}, "
                            f"清空了约{args_tokens} token的args",
                            extra={"tag": "LARGE_RESULT_OPTIMIZE"}
                        )
                    else:
                        new_tool_calls.append(tc)

                if modified:
                    # 创建新的 AIMessage，保留其他属性
                    new_msg = AIMessage(
                        content=msg.content,
                        id=msg.id,
                        tool_calls=new_tool_calls,
                        additional_kwargs={
                            **getattr(msg, "additional_kwargs", {}),
                            "tool_calls_optimized": True
                        }
                    )
                    # 复制 index 属性
                    if hasattr(msg, 'index') and msg.index is not None:
                        new_msg.index = msg.index
                    result.append(new_msg)
                    continue

        result.append(msg)

    if optimized_count > 0:
        logger.info(
            f"大结果优化: 处理了{optimized_count}个大结果工具调用，"
            f"估算节省{saved_tokens} tokens",
            extra={"tag": "LARGE_RESULT_OPTIMIZED"}
        )

    return result, optimized_count, saved_tokens


def process_messages_before_send(
    messages: list,
    logger: logging.Logger = None,
    truncate: bool = True,
    generate_prompts: bool = True
) -> Tuple[list, dict]:
    """
    发送给模型前的统一消息处理入口

    处理流程：
    1. 空消息清理（检测连续空content的消息段并丢弃）
    2. 大结果优化（清空大 ToolMessage 对应 tool_calls 的 args）
    3. Token 截断（如果需要）
    4. 生成压缩提示

    注意：消息验证和修复逻辑已转移到 message_validator 模块，
    在持久化恢复和 model_node 中统一处理。

    Args:
        messages: 原始消息列表
        logger: 可选的日志记录器
        truncate: 是否执行 token 截断
        generate_prompts: 是否生成压缩提示

    Returns:
        (处理后的消息列表, 处理信息字典)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    result = list(messages)
    info = {
        "truncated": False,
        "optimized": False,
        "optimized_count": 0,
        "saved_tokens": 0,
        "cleanup_done": False,
        "cleanup_count": 0,
        "cleanup_removed": 0,
        "removed_count": 0,
        "removed_items": [],
        "prompts_added": 0,
        "original_token": 0,
        "final_token": 0
    }

    # 记录原始 token（处理前）
    info["original_token"] = estimate_messages_tokens(result)
    logger.info(f"process_messages_before_send 处理前: {info['original_token']} tokens, {len(result)} 条消息",
                extra={'tag': 'MSG_PROCESS_START'})

    # 1. 空消息清理（检测连续空content段并丢弃）
    result, cleanup_count, cleanup_removed, cleanup_info_list = _cleanup_empty_messages(result, logger)
    if cleanup_count > 0:
        info["cleanup_done"] = True
        info["cleanup_count"] = cleanup_count
        info["cleanup_removed"] = cleanup_removed

    # 2. 大结果优化（清空大结果对应 tool_calls 的 args）
    result, optimized_count, saved_tokens = _optimize_large_tool_results(result, logger)
    if optimized_count > 0:
        info["optimized"] = True
        info["optimized_count"] = optimized_count
        info["saved_tokens"] = saved_tokens

    # 3. Token 截断（如果仍然超过限制）
    if truncate:
        result, was_truncated, removed_count, removed_items = truncate_messages_for_token_limit(
            result, logger
        )
        info["truncated"] = was_truncated
        info["removed_count"] = removed_count
        info["removed_items"] = removed_items

    # 3. Token 截断后的处理（截断可能破坏工具调用链）
    # 注意：完整的验证修复逻辑已转移到 message_validator 模块
    # 在持久化恢复和 model_node 中统一处理

    # 4. 统一追加提示消息（先追加空消息清理提示，再追加压缩提示）
    # 4.1 追加空消息清理提示（合并为一条总提示，放在消息列表末尾）
    if cleanup_info_list:
        # 构建合并的提示内容
        cleanup_details = []
        total_removed = 0
        for first_msg_idx, last_msg_idx, count in cleanup_info_list:
            cleanup_details.append(f"消息index {first_msg_idx}-{last_msg_idx} 的 {count} 条")
            total_removed += count

        # 生成一条总的提示消息
        cleanup_content = "[空消息清理] " + "; ".join(cleanup_details) + " 已自动移除"
        cleanup_msg = HumanMessage(
            content=cleanup_content,
            additional_kwargs={
                "auto_cleanup": True,
                "cleanup_batches": cleanup_info_list,  # 保留原始信息供参考
                "total_removed": total_removed
            }
        )
        result.append(cleanup_msg)
        logger.info(f"追加空消息清理提示: 共 {len(cleanup_info_list)} 批，移除 {total_removed} 条消息", extra={'tag': 'CLEANUP_PROMPTS_ADDED'})

    # 4.2 追加压缩提示（原有的生成压缩提示功能）
    if generate_prompts:
        prompts = generate_compress_prompts(result, logger)
        if prompts:
            result.extend(prompts)
            info["prompts_added"] = len(prompts)

    info["final_token"] = estimate_messages_tokens(result)
    logger.info(f"process_messages_before_send 处理后: {info['final_token']} tokens ("
                f"空消息清理={info['cleanup_done']}, "
                f"大结果优化={info['optimized']}, "
                f"截断={info['truncated']}, "
                f"提示={info['prompts_added']})",
                extra={'tag': 'MSG_PROCESS_END'})

    return result, info
