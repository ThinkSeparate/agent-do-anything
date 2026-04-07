# core/plan/state_define.py
from typing import Annotated, TypedDict, Optional, List, Dict, Any
from langgraph.graph.message import add_messages


class PlanState(TypedDict):
    """Plan Agent 状态定义"""
    messages: Annotated[list, add_messages]
    # 规划相关状态
    original_task: str                    # 原始任务
    plan_tree: Optional[Dict[str, Any]]   # 任务树结构
    completed_tasks: List[Dict[str, Any]] # 已完成任务
    pending_tasks: List[Dict[str, Any]]   # 待处理任务
    current_phase: str                    # 当前阶段: planning, executing, replanning
    execution_context: Dict[str, Any]     # 执行上下文
    consecutive_failures: int             # 连续失败次数
    max_failures: int                     # 最大允许失败次数 (默认3)