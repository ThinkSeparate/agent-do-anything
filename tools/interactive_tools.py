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


# 这是短任务模式的结束工具。
@tool
def submit_final_answer(content: str) -> str:
    """
    当你确信已收集到所有必要信息，并可以回答被分配的问题时，调用此工具来提交最终答案。
    """
    return f"[任务完成] 最终答案已提交。框架处理中。\n你的最终答案 (content): {content}"

# 长任务模式：子任务完成提交工具（非阻塞）
@tool
def submit_sub_task(content: str) -> str:
    """
    当你完成当前子任务时，调用此工具提交结果。
    系统会记录你的完成内容，并等待用户的下一个指令。

    Args:
        content: 当前子任务的完成内容以及所有想提交给用户的信息
    """
    return content


# 短任务模式工具
short_task_tools = [ask_user, submit_final_answer]

# 长任务模式工具
long_task_tools = [ask_user, submit_sub_task]