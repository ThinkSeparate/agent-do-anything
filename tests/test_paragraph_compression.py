#!/usr/bin/env python3
"""
测试段落压缩功能
"""
# 测试脚本位置: tests/test_paragraph_compression.py

import sys
sys.path.insert(0, 'D:\\workspace\\agent_do_anything')

from langchain.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, RemoveMessage
from langchain_core.messages import BaseMessage

# 模拟 execute_paragraph_compression 函数（从 tool_node.py 复制）
def execute_paragraph_compression(messages, start_idx, end_idx, summary_text):
    """
    执行段落压缩测试
    """
    updates = []

    # 验证参数
    if not isinstance(start_idx, int) or not isinstance(end_idx, int):
        return [], "段落压缩失败：start_index和end_index必须是整数"
    if not summary_text or not summary_text.strip():
        return [], "段落压缩失败：summary不能为空"
    if start_idx <= 1 or end_idx <= 1:
        print(f"段落压缩：禁止包含系统消息(0)或用户消息(1)")
        return [], "段落压缩失败：禁止包含索引0或1"
    if not (0 <= start_idx < len(messages) and 0 <= end_idx < len(messages)):
        print(f"段落压缩：索引越界")
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
        return [], f"段落压缩失败：范围内第一个工具相关消息（索引{first_idx}）必须是AIMessage且有tool_calls"

    # 最后一个工具相关消息必须是 ToolMessage
    last_idx, last_msg, last_is_tool_call = tool_related_msgs[-1]
    if last_is_tool_call:
        return [], f"段落压缩失败：范围内最后一个工具相关消息（索引{last_idx}）必须是ToolMessage"

    try:
        # 1. 使用 start_idx 消息的ID创建总结消息
        first_msg = messages[start_idx]
        summary_msg = AIMessage(
            content=f"[段落总结] {summary_text}",
            id=first_msg.id,
            additional_kwargs={
                **getattr(first_msg, "additional_kwargs", {}),
                "compressed": True,
                "is_paragraph_summary": True,
                "original_range": f"{start_idx}-{end_idx}"
            }
        )
        updates.append(summary_msg)

        # 2. 删除其余消息
        for idx in range(start_idx + 1, end_idx + 1):
            target_msg = messages[idx]
            updates.append(RemoveMessage(id=target_msg.id))

        print(f"段落压缩：索引{start_idx}-{end_idx}已替换为总结")
        return updates, f"段落压缩：{start_idx}-{end_idx}替换为总结"

    except Exception as e:
        print(f"段落压缩执行失败: {e}")
        return [], f"段落压缩失败: {e}"


def create_test_messages():
    """创建测试消息列表"""
    messages = []

    # [0] SystemMessage
    messages.append(SystemMessage(content="系统提示"))

    # [1] HumanMessage
    messages.append(HumanMessage(content="用户问题"))

    # [2] AIMessage (无 tool_calls)
    messages.append(AIMessage(content="初步思考"))

    # [3] AIMessage (有 tool_calls)
    messages.append(AIMessage(
        content="调用工具",
        tool_calls=[{"name": "read_file", "args": {"file_path": "test.txt"}, "id": "tc_1", "type": "tool_call"}]
    ))

    # [4] ToolMessage
    messages.append(ToolMessage(
        content="文件内容",
        tool_call_id="tc_1"
    ))

    # [5] HumanMessage (中间的用户消息)
    messages.append(HumanMessage(content="用户追问"))

    # [6] AIMessage (有 tool_calls)
    messages.append(AIMessage(
        content="再次调用",
        tool_calls=[{"name": "list_directory", "args": {"dir": "."}, "id": "tc_2", "type": "tool_call"}]
    ))

    # [7] ToolMessage
    messages.append(ToolMessage(
        content="目录列表",
        tool_call_id="tc_2"
    ))

    # [8] AIMessage
    messages.append(AIMessage(content="总结回答"))

    return messages


def print_messages(messages, title="消息列表"):
    """打印消息列表"""
    print(f"\n{'='*50}")
    print(title)
    print('='*50)
    for i, msg in enumerate(messages):
        tool_calls = getattr(msg, 'tool_calls', None)
        tool_call_info = f" (tool_calls: {len(tool_calls)})" if tool_calls else ""
        print(f"[{i}] {type(msg).__name__}{tool_call_info}: {msg.content[:50]}...")


def main():
    print("测试段落压缩功能")
    print("="*50)

    # 创建测试消息
    messages = create_test_messages()
    print_messages(messages, "原始消息列表")

    # 测试1: 正常压缩 (3-4, tool_call -> tool_result)
    print("\n" + "="*50)
    print("测试1: 压缩索引 3-4 (AIMessage(tool_call) -> ToolMessage)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 3, 4, "读取文件完成")
    print(f"结果: {desc}")
    print(f"返回 {len(updates)} 个更新:")
    for u in updates:
        if isinstance(u, RemoveMessage):
            print(f"  - RemoveMessage(id={u.id})")
        else:
            print(f"  - {type(u).__name__}(content={u.content[:30]}..., id={u.id})")

    # 测试2: 包含用户消息的压缩 (5-7)
    print("\n" + "="*50)
    print("测试2: 压缩索引 5-7 (包含用户消息)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 5, 7, "列出目录完成")
    print(f"结果: {desc}")
    print(f"返回 {len(updates)} 个更新:")
    for u in updates:
        if isinstance(u, RemoveMessage):
            print(f"  - RemoveMessage(id={u.id})")
        else:
            print(f"  - {type(u).__name__}(content={u.content[:30]}..., id={u.id})")

    # 测试3: 错误测试 - 第一个是ToolMessage
    print("\n" + "="*50)
    print("测试3: 错误 - 范围以ToolMessage开始 (4-5)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 4, 5, "错误测试")
    print(f"结果: {desc}")

    # 测试4: 错误测试 - 最后一个是AIMessage+tool_calls
    print("\n" + "="*50)
    print("测试4: 错误 - 范围以AIMessage(tool_call)结束 (6-7, 但7是ToolMessage所以应该成功)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 6, 7, "应该成功")
    print(f"结果: {desc}")

    # 测试5: 跨越系统消息/用户消息
    print("\n" + "="*50)
    print("测试5: 错误 - 跨越索引0或1 (0-3)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 0, 3, "跨越测试")
    print(f"结果: {desc}")

    # 测试6: start_index >= end_index
    print("\n" + "="*50)
    print("测试6: 错误 - start_index >= end_index (3-3)")
    print("="*50)
    updates, desc = execute_paragraph_compression(messages, 3, 3, "相同索引测试")
    print(f"结果: {desc}")


if __name__ == "__main__":
    main()
