# core/common/state_define.py
from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Agent 状态定义，用于 LangGraph 图的状态管理。"""
    messages: Annotated[list, add_messages]
    consecutive_failures: int
    status: Optional[str]
