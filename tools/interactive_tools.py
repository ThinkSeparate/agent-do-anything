# tools/interactive_tools.py
from langchain_core.tools import tool


@tool
def ask_user(prompt: str) -> str:
    """向用户提问并获取其输入。用于在指令不完备时进行交互。"""
    try:
        user_response = input(f"\n❓ {prompt}\n您的回复: ")
        return user_response.strip()
    except Exception as e:
        return f"询问用户时发生错误: {e}"


interactive_tools = [ask_user]
