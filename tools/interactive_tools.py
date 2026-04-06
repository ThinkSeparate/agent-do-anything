# tools/interactive_tools.py
from langchain_core.tools import tool


@tool
def ask_user(prompt: str) -> str:
    """向用户提问并获取其输入。用于在指令不完备、需要澄清或获取额外信息时进行交互。"""
    try:
        user_response = input(f"\n❓ {prompt}\n您的回复: ")
        return user_response.strip()
    except Exception as e:
        return f"询问用户时发生错误: {e}"


@tool
def submit_final_answer(content: str) -> str:
    """
    当你确信已收集到所有必要信息，并可以回答用户最初提出的问题时，调用此工具来提交最终答案。
    """
    # 在实际的Agent框架中，此处通常会触发一个“任务完成”事件，并返回最终答案。
    # 这里返回一个确认消息，模拟框架的响应。
    return f"[任务完成] 最终答案已提交。框架处理中。\n你的最终答案 (content): {content}"


@tool
def transfer_to_react(clarified_task_description: str) -> str:
    """
    当你确认用户的需求涉及复杂的文件、系统、网络或文档操作，无法仅通过对话完成时，调用此工具。
    这会将已澄清的、明确的任务描述转交给专业的执行Agent（ReActAgent）进行处理。
    """
    # 此工具在框架内的实际作用是让LangGraph图路由到“transfer_react”节点。
    # 工具本身的返回内容不重要，重要的是触发了状态转移。
    return f"[需求转移] 已确认此为复杂操作需求。任务描述已传递至执行Agent。\n传递的任务描述: {clarified_task_description}"

# 更新 interactive_tools 列表，添加新工具
interactive_tools = [ask_user, submit_final_answer, transfer_to_react]