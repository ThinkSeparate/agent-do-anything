# core/react/agent_logic.py
from typing import Literal
from core.common.state_define import AgentState


def should_continue(state: AgentState) -> Literal["tools", "end_normal", "end_abort"]:
    """
    路由函数：根据模型的最新输出决定下一步流程。

    决策逻辑：
    1. 如果模型发出的 `tool_calls` 列表为空 -> 模型尝试直接给出最终答案，视为"异常中止"，路由到 `"end_abort"`。
    2. 如果 `tool_calls` 不为空，检查第一个工具调用（通常只有一个）的名称：
        a. 如果是 `submit_final_answer` 或 `wait_for_next_task` -> 模型通过正式流程提交答案或等待下一个任务，视为"正常结束"，路由到 `"end_normal"`。
        b. 如果是其他任何工具 -> 模型需要继续执行，路由到 `"tools"`。
    """
    messages = state["messages"]
    last_message = messages[-1]

    # 情况1: 模型没有调用任何工具，直接返回了文本内容
    if not last_message.tool_calls:
        # 这是您定义的"异常退出"情况
        return "end_abort"

    # 情况2: 模型调用了工具
    # 通常一次只调用一个工具，我们检查第一个工具调用
    first_tool_call = last_message.tool_calls[0]
    tool_name = first_tool_call.get("name", "")

    if tool_name in ("submit_final_answer", "wait_for_next_task"):
        # 模型通过专用工具提交最终答案或等待下一个任务，这是"正常退出"
        return "end_normal"
    else:
        # 模型调用了其他工具，需要继续执行
        return "tools"
