# tools/clarify_special_tools.py (新增，特定于澄清流程的工具)
from langchain_core.tools import tool


@tool
def transfer_to_react(clarified_task_description: str) -> str:
    """
    当你确认用户的需求涉及复杂的文件、系统、网络或文档操作，无法仅通过对话完成时，调用此工具。
    这会将已澄清的、明确的任务描述转交给专业的执行Agent（ReActAgent）进行处理。
    """
    return f"[需求转移] 已确认此为复杂操作需求。任务描述已传递至执行Agent。\n传递的任务描述: {clarified_task_description}"


# 特定于澄清流程的工具
clarify_special_tools = [transfer_to_react]