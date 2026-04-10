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

# 这是长任务模式的结束工具。
@tool
def wait_for_next_task(summary: str) -> str:
    """
    当你完成当前子任务时调用此工具。
    系统会等待用户输入下一个任务。

    Args:
        summary: 当前子任务的完成总结

    Returns:
        用户的下一个指令
    """
    print(f"\n✅ {summary}")
    print("-" * 50)
    user_input = input("输入 done 结束对话，或继续输入新任务:\n> ").strip()
    return user_input


# 短任务模式工具（只有 submit_final_answer）
short_task_tools = [ask_user, submit_final_answer]

# 长任务模式工具（只有 wait_for_next_task）
long_task_tools = [ask_user, wait_for_next_task]