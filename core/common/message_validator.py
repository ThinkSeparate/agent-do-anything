# core/common/message_validator.py
"""
消息验证和修复模块

提供消息完整性验证和修复功能，支持：
1. 自动修复尾部异常消息
2. 检测完整消息列表异常
3. 带用户确认的中间位置修复

状态管理：
- corrupted: 消息损坏且用户拒绝修复，任务结束（不可恢复）
"""

import logging
from typing import List, Tuple, Dict, Any
from langchain.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage


class MessageValidationError(Exception):
    """消息验证失败且用户拒绝修复，任务不可恢复"""
    pass


def fix_tail_messages(messages: list, logger: logging.Logger = None) -> Tuple[list, int, str]:
    """
    自动修复尾部异常消息（用于持久化恢复后）。

    策略：
    - 只检查消息列表尾部，从后向前移除异常消息
    - 循环移除，直到尾部消息合法或消息列表为空
    - 异常情况：
      1. 尾部是 ToolMessage（没有前置 AIMessage 匹配）
      2. 尾部是 AIMessage 且有 tool_calls 但没有对应的 ToolMessage

    Returns:
        (修复后的消息列表, 移除的消息数量, 移除描述)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    result = list(messages)
    removed_count = 0
    removed_desc = ""

    while len(result) > 0:
        last_msg = result[-1]

        # 场景1: 尾部是孤立的 ToolMessage
        if isinstance(last_msg, ToolMessage):
            tc_id = getattr(last_msg, "tool_call_id", None)
            # 检查前面是否有匹配的 AIMessage
            found_match = False
            for msg in reversed(result[:-1]):
                if isinstance(msg, AIMessage):
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    expected_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
                    if tc_id in expected_ids:
                        found_match = True
                        break

            if not found_match:
                # 孤立的 ToolMessage，移除
                result = result[:-1]
                removed_count += 1
                removed_desc = f"孤立ToolMessage(tool_call_id={tc_id})"
                logger.warning(f"尾部修复: 移除{removed_desc}", extra={"tag": "TAIL_FIX"})
                continue  # 继续检查新的尾部
            else:
                # 找到匹配，尾部合法，停止
                break

        # 场景2: 尾部是 AIMessage 且有 tool_calls 但没有对应的 ToolMessage
        elif isinstance(last_msg, AIMessage):
            tool_calls = getattr(last_msg, "tool_calls", None) or []
            if tool_calls:
                # 清空 tool_calls 并保留消息
                logger.warning(f"尾部修复: 清空AIMessage的{len(tool_calls)}个tool_calls",
                              extra={"tag": "TAIL_FIX"})
                fixed_msg = AIMessage(
                    content=last_msg.content,
                    id=last_msg.id,
                    tool_calls=[],
                    additional_kwargs={
                        **getattr(last_msg, "additional_kwargs", {}),
                        "tool_calls_fixed": True,
                        "original_tool_calls_count": len(tool_calls)
                    }
                )
                if hasattr(last_msg, 'index') and last_msg.index is not None:
                    fixed_msg.index = last_msg.index
                result[-1] = fixed_msg
                removed_desc = f"未完成工具调用({len(tool_calls)}个)"
                break
            else:
                # 没有 tool_calls，合法
                break
        else:
            # HumanMessage 或 SystemMessage，合法
            break

    if removed_count > 0:
        logger.info(f"尾部修复完成: 移除了{removed_count}条消息", extra={"tag": "TAIL_FIXED"})

    return result, removed_count, removed_desc


def validate_full_messages(messages: list, logger: logging.Logger = None) -> Tuple[bool, List[Dict]]:
    """
    完整验证消息列表。

    策略：
    - 遍历整个消息列表，检测所有异常
    - 异常情况：
      1. 孤立的 ToolMessage（前面没有匹配的 AIMessage）
      2. AIMessage 有 tool_calls 但后面没有对应的 ToolMessage

    Returns:
        (是否有效, 异常列表)
        异常列表: [{"index": int, "type": str, "description": str}, ...]
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    issues = []

    for i, msg in enumerate(messages):
        # 检查 ToolMessage 是否孤立
        if isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            found_match = False
            for prev_msg in reversed(messages[:i]):
                if isinstance(prev_msg, AIMessage):
                    tool_calls = getattr(prev_msg, "tool_calls", None) or []
                    expected_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
                    if tc_id in expected_ids:
                        found_match = True
                        break

            if not found_match:
                issues.append({
                    "index": i,
                    "type": "ToolMessage",
                    "description": f"孤立ToolMessage(tool_call_id={tc_id})"
                })

        # 检查 AIMessage 的 tool_calls 是否完整
        elif isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                expected_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
                found_tools = set()
                for next_msg in messages[i+1:]:
                    if isinstance(next_msg, ToolMessage):
                        if next_msg.tool_call_id in expected_ids:
                            found_tools.add(next_msg.tool_call_id)
                            if len(found_tools) == len(expected_ids):
                                break
                    elif isinstance(next_msg, AIMessage):
                        # 遇到下一个 AIMessage，停止查找
                        break

                missing = expected_ids - found_tools
                if missing:
                    issues.append({
                        "index": i,
                        "type": "AIMessage",
                        "description": f"缺少{len(missing)}个ToolMessage响应"
                    })

    is_valid = len(issues) == 0

    if issues:
        logger.warning(f"完整验证: 发现{len(issues)}处异常", extra={"tag": "VALIDATION_ISSUES"})
        for issue in issues:
            logger.warning(f"  - 索引{issue['index']} ({issue['type']}): {issue['description']}")
    else:
        logger.info(f"完整验证: 消息列表完整", extra={"tag": "VALIDATION_OK"})

    return is_valid, issues


def repair_messages(messages: list, issues: List[Dict], logger: logging.Logger = None) -> Tuple[list, int, int]:
    """
    修复消息列表中的异常。

    策略：
    - 孤立 ToolMessage: 移除
    - AIMessage 缺少 ToolMessage: 清空 tool_calls

    Returns:
        (修复后的消息列表, 移除数量, 修复数量)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    result = list(messages)
    removed_count = 0
    fixed_count = 0

    # 从后向前处理，避免索引变化
    for issue in sorted(issues, key=lambda x: x["index"], reverse=True):
        idx = issue["index"]
        if idx >= len(result):
            continue

        msg = result[idx]

        if issue["type"] == "ToolMessage":
            # 移除孤立 ToolMessage
            result.pop(idx)
            removed_count += 1
            logger.info(f"修复: 移除索引{idx}的孤立ToolMessage", extra={"tag": "REPAIR"})

        elif issue["type"] == "AIMessage":
            # 清空 tool_calls
            tool_calls = getattr(msg, "tool_calls", None) or []
            fixed_msg = AIMessage(
                content=msg.content,
                id=msg.id,
                tool_calls=[],
                additional_kwargs={
                    **getattr(msg, "additional_kwargs", {}),
                    "tool_calls_fixed": True,
                    "original_tool_calls_count": len(tool_calls)
                }
            )
            if hasattr(msg, 'index') and msg.index is not None:
                fixed_msg.index = msg.index
            result[idx] = fixed_msg
            fixed_count += 1
            logger.info(f"修复: 清空索引{idx}的AIMessage的{len(tool_calls)}个tool_calls", extra={"tag": "REPAIR"})

    logger.info(f"修复完成: 移除{removed_count}条，修复{fixed_count}条", extra={"tag": "REPAIR_DONE"})
    return result, removed_count, fixed_count


def validate_and_repair(
    messages: list,
    logger: logging.Logger = None
) -> Tuple[bool, list]:
    """
    统一的消息验证和修复流程。

    流程：
    1. 自动修复尾部异常
    2. 完整验证消息完整性
    3. 如果完整 -> 流程结束，返回成功
    4. 如果不完整 -> 询问用户是否修复
       * 用户同意 -> 完整修复 -> 返回成功
       * 用户拒绝 -> 抛出 MessageValidationError -> 由外层统一标记 corrupted

    Args:
        messages: 消息列表
        logger: 日志记录器

    Returns:
        (是否成功, 处理后的消息列表)
        - 成功: (True, messages)
        - 失败: 抛出 MessageValidationError（不再返回 False）
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    original_messages = list(messages)

    # 步骤1: 自动修复尾部
    messages, tail_removed, tail_desc = fix_tail_messages(messages, logger)

    # 步骤2: 完整验证
    is_valid, issues = validate_full_messages(messages, logger)

    if is_valid:
        # 只有尾部修复或无需修复
        return True, messages

    # 步骤3: 发现问题，中间位置不完整，询问用户
    logger.warning(f"消息验证: 发现{len(issues)}处异常", extra={"tag": "VALIDATION_ISSUES"})

    # 构建询问内容
    issue_desc = "\n".join([
        f"  - 索引{i['index']} ({i['type']}): {i['description']}"
        for i in issues[:5]  # 最多显示5条
    ])
    if len(issues) > 5:
        issue_desc += f"\n  ... 还有 {len(issues) - 5} 处异常"

    print("\n" + "=" * 60)
    print("⚠️  消息上下文损坏")
    print("=" * 60)
    print(f"检测到 {len(issues)} 处消息异常:\n{issue_desc}\n")
    print("【场景说明】")
    print("历史消息中出现断裂：工具调用和返回不匹配，或存在孤立消息。")
    print("这通常是由于程序异常中断、强制退出或数据损坏导致的。\n")
    print("【修复影响】")
    print("- 将删除孤立的 ToolMessage（工具返回结果）")
    print("- 将清空不完整的 AIMessage tool_calls（未完成的工具调用）")
    print("- 修复后可能丢失部分历史上下文，但任务可以继续\n")
    print("【你的选择】")
    print("- 输入 'yes'：同意修复，删除异常消息，继续当前任务")
    print("- 输入 'no' ：拒绝修复，结束任务，该会话将标记为不可用")
    print("=" * 60)

    # 循环直到用户给出明确的 yes 或 no
    while True:
        user_response = input("> 你的选择: ").strip().lower()

        if user_response == 'yes':
            # 用户同意修复
            messages, removed, fixed = repair_messages(messages, issues, logger)
            logger.info(f"用户确认修复: 移除{removed}条，修复{fixed}条", extra={"tag": "USER_CONFIRM_REPAIR"})
            return True, messages
        elif user_response == 'no':
            # 用户拒绝修复，抛出异常让外层统一处理持久化状态
            logger.error("用户拒绝修复，任务标记为损坏不可恢复", extra={"tag": "USER_REJECT_REPAIR"})
            raise MessageValidationError(
                "消息上下文损坏且用户拒绝修复"
            )
        else:
            # 无效输入，提示后重新询问
            print("⚠️  无效输入，请输入 'yes' 或 'no'")
