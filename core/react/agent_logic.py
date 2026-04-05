# core/react/agent_logic.py
from typing import Literal
from core.common.state_define import AgentState


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """
    路由函数：根据模型输出决定下一步。

    - 如果模型发出 tool_calls → 继续执行工具
    - 否则（最终回复）→ 结束
    """
    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tools"
    return "end"
