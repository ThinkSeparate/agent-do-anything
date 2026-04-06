# core/clarify/agent_logic.py
from typing import Literal
from core.common.state_define import AgentState

def should_continue(state: AgentState) -> Literal["ask_user", "end_direct", "transfer_react"]:
    """
    需求澄清Agent的路由函数。
    如果模型没有调用工具，我们要求它重新思考。
    """
    messages = state["messages"]
    last_message = messages[-1]

    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        # 模型没有调用工具，我们需要强制它重新思考
        return "ask_user"  # 返回到模型节点重新思考

    first_tool_call = last_message.tool_calls[0]
    tool_name = first_tool_call.get("name", "")

    if tool_name == "ask_user":
        return "ask_user"
    elif tool_name == "submit_final_answer":
        return "end_direct"
    elif tool_name == "transfer_to_react":
        return "transfer_react"
    else:
        # 未知工具调用，返回到模型重新思考
        return "ask_user"