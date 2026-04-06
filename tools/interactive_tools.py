# tools/interactive_tools.py (重构，只保留通用交互工具)
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
    return f"[任务完成] 最终答案已提交。框架处理中。\n你的最终答案 (content): {content}"


# 更新列表，只包含通用交互工具
general_interactive_tools = [ask_user, submit_final_answer]