# tools/clarify_special_tools.py (修改)
from langchain_core.tools import tool


@tool
def transfer_to_react(clarified_task_description: str) -> str:
    """
    当你确认用户的需求涉及复杂的文件、系统、网络或文档操作，无法仅通过对话完成时，调用此工具。
    这会将已澄清的、明确的任务描述转交给规划Agent（PlanAgent）进行处理。
    """
    return f"[需求转移] 已确认此为复杂操作需求。任务描述已传递至规划Agent。\n传递的任务描述: {clarified_task_description}"


# 特定于澄清流程的工具
clarify_special_tools = [transfer_to_react]