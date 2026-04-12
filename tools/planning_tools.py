# tools/planning_tools.py
from langchain_core.tools import tool
from langchain.messages import HumanMessage
from typing import Optional, Dict, Any, List
import json


@tool
def assign_task_to_react(task_description: str, task_id: Optional[str] = None) -> str:
    """将一个子任务分配给 ReAct Agent 执行。由 PlanAgent 内部处理。"""
    # 这里的实际调用将由 PlanAgent 在运行时注入
    return f"[任务分配] 任务 '{task_description}' 已分配给 ReAct Agent 处理。\n任务ID: {task_id or '未指定'}"


@tool
def replan_tool(
    original_plan: str,
    failure_reason: str,
    execution_context: Optional[str] = None
) -> str:
    """当计划执行失败或需要调整时，调用此工具重新规划。由 PlanAgent 内部处理。"""
    return f"[重新规划] 基于失败原因 '{failure_reason}' 重新评估计划。\n原始计划: {original_plan}"


@tool
def submit_plan_report(final_report: str, plan_tree: Optional[str] = None) -> str:
    """提交最终的计划执行报告。由 PlanAgent 内部处理。"""
    return f"[计划完成] 最终报告已提交。\n报告长度: {len(final_report)} 字符"


# 规划工具集
planning_tools = [assign_task_to_react, replan_tool, submit_plan_report]