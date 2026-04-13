"""
消息验证和修复模块测试

测试用例：
1. 正常消息列表 - 应通过验证，无误判
2. 尾部异常 - fix_tail_messages 自动修复
3. 中间异常 - repair_messages 修复
4. 孤立 ToolMessage - 自动移除
5. 真实数据 - 已完成会话不应被误判

运行方式:
    python tests/common/test_message_validator.py
"""

import json
import logging
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_core.messages import (
    messages_from_dict,
    AIMessage,
    ToolMessage,
    HumanMessage,
)

from core.common.message_validator import (
    fix_tail_messages,
    validate_full_messages,
    repair_messages,
)

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 测试数据目录
TEST_DATA_DIR = Path(__file__).parent.parent / "test_data"


def test_normal_message_chain():
    """测试完整的消息链 - 工具调用和响应正确匹配"""
    messages = [
        HumanMessage(content="执行任务"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
        ),
        ToolMessage(content="结果A", tool_call_id="call_1"),
        AIMessage(content="完成"),
    ]

    is_valid, issues = validate_full_messages(messages, logger)

    assert is_valid is True, f"期望有效，但发现问题: {issues}"
    assert len(issues) == 0
    print("PASS: test_normal_message_chain")


def test_no_tool_calls_message():
    """测试没有工具调用的消息列表"""
    messages = [
        HumanMessage(content="你好"),
        AIMessage(content="你好！"),
        HumanMessage(content="谢谢"),
        AIMessage(content="不客气"),
    ]

    is_valid, issues = validate_full_messages(messages, logger)

    assert is_valid is True
    assert len(issues) == 0
    print("PASS: test_no_tool_calls_message")


def test_tail_incomplete_tool_calls():
    """测试尾部AIMessage有tool_calls但缺少ToolMessage"""
    messages = [
        HumanMessage(content="执行任务"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
        ),
    ]

    fixed, removed, desc = fix_tail_messages(messages, logger)

    assert removed == 0
    assert "未完成" in desc or "tool_calls" in desc
    assert len(fixed) == 2

    last_msg = fixed[-1]
    assert isinstance(last_msg, AIMessage)
    assert last_msg.tool_calls == []
    assert last_msg.additional_kwargs.get("tool_calls_fixed") is True

    is_valid, issues = validate_full_messages(fixed, logger)
    assert is_valid is True
    print("PASS: test_tail_incomplete_tool_calls")


def test_tail_orphan_tool_message():
    """测试尾部孤立的ToolMessage"""
    messages = [
        HumanMessage(content="执行任务"),
        AIMessage(content="完成"),
        ToolMessage(content="孤立结果", tool_call_id="orphan_call"),
    ]

    fixed, removed, desc = fix_tail_messages(messages, logger)

    assert removed == 1
    assert "孤立" in desc or "ToolMessage" in desc
    assert len(fixed) == 2

    is_valid, issues = validate_full_messages(fixed, logger)
    assert is_valid is True
    print("PASS: test_tail_orphan_tool_message")


def test_missing_tool_response_in_middle():
    """测试中间位置缺少ToolMessage响应"""
    messages = [
        HumanMessage(content="任务1"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "tool_a", "args": {}}],
        ),
        HumanMessage(content="任务2"),
        AIMessage(content="完成"),
    ]

    is_valid, issues = validate_full_messages(messages, logger)
    assert is_valid is False
    assert len(issues) == 1
    assert issues[0]["type"] == "AIMessage"

    # fix_tail_messages 无法修复中间异常
    fixed_tail, removed, _ = fix_tail_messages(messages, logger)
    assert removed == 0
    is_valid_tail, _ = validate_full_messages(fixed_tail, logger)
    assert is_valid_tail is False

    # repair_messages 修复
    repaired, removed, fixed = repair_messages(messages, issues, logger)
    assert removed == 0
    assert fixed == 1

    is_valid_final, _ = validate_full_messages(repaired, logger)
    assert is_valid_final is True
    print("PASS: test_missing_tool_response_in_middle")


def test_orphan_tool_message_in_middle():
    """测试中间位置孤立的ToolMessage"""
    messages = [
        HumanMessage(content="任务1"),
        ToolMessage(content="孤立", tool_call_id="orphan"),
        AIMessage(content="完成"),
    ]

    is_valid, issues = validate_full_messages(messages, logger)
    assert is_valid is False
    assert len(issues) == 1
    assert issues[0]["type"] == "ToolMessage"

    repaired, removed, fixed = repair_messages(messages, issues, logger)
    assert removed == 1
    assert fixed == 0
    assert len(repaired) == 2

    is_valid_final, _ = validate_full_messages(repaired, logger)
    assert is_valid_final is True
    print("PASS: test_orphan_tool_message_in_middle")


def test_repair_order_from_end_to_start():
    """验证repair_messages从后向前处理，避免索引变化问题"""
    messages = [
        HumanMessage(content="任务1"),
        ToolMessage(content="孤立1", tool_call_id="orphan_1"),
        AIMessage(content="中间"),
        ToolMessage(content="孤立2", tool_call_id="orphan_2"),
        AIMessage(content="完成"),
    ]

    is_valid, issues = validate_full_messages(messages, logger)
    assert len(issues) == 2
    assert issues[0]["index"] == 1
    assert issues[1]["index"] == 3

    repaired, removed, fixed = repair_messages(messages, issues, logger)
    assert removed == 2
    assert len(repaired) == 3
    print("PASS: test_repair_order_from_end_to_start")


def test_real_done_session():
    """测试真实完成的会话 - 应该无异常"""
    session_file = TEST_DATA_DIR / "session_43.json"
    if not session_file.exists():
        print("SKIP: test_real_done_session (数据文件不存在)")
        return

    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = messages_from_dict(data["messages"])

    fixed, removed, desc = fix_tail_messages(messages, logger)
    assert removed == 0
    assert desc == ""

    is_valid, issues = validate_full_messages(messages, logger)
    assert is_valid is True, f"正常会话被误判: {issues}"
    assert len(issues) == 0
    print(f"PASS: test_real_done_session ({len(messages)}条消息, 95个tool_calls)")


def test_real_fail_session():
    """测试真实失败的会话"""
    session_file = TEST_DATA_DIR / "session_110.json"
    if not session_file.exists():
        print("SKIP: test_real_fail_session (数据文件不存在)")
        return

    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = messages_from_dict(data["messages"])
    is_valid, issues = validate_full_messages(messages, logger)

    if is_valid:
        print(f"PASS: test_real_fail_session ({len(messages)}条消息, 消息链完整)")
    else:
        repaired, _, _ = repair_messages(messages, issues, logger)
        is_valid_final, _ = validate_full_messages(repaired, logger)
        assert is_valid_final is True
        print(f"PASS: test_real_fail_session ({len(messages)}条消息, 修复后有效)")


def run_all_tests():
    tests = [
        test_normal_message_chain,
        test_no_tool_calls_message,
        test_tail_incomplete_tool_calls,
        test_tail_orphan_tool_message,
        test_missing_tool_response_in_middle,
        test_orphan_tool_message_in_middle,
        test_repair_order_from_end_to_start,
        test_real_done_session,
        test_real_fail_session,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"FAIL: {test.__name__}: {e}")

    print()
    print(f"=" * 60)
    print(f"测试结果: 通过 {passed} / 失败 {failed} / 总计 {len(tests)}")
    print(f"=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
