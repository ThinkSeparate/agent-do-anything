# tools/system_tools.py
import os
from langchain_core.tools import tool
from core.sandbox import get_sandbox_executor


@tool
def run_terminal_command(command: str, think: str = "") -> str:
    """
    执行终端命令。

    支持自动授权策略：根据配置的安全策略，部分命令会自动执行，
    危险命令会要求确认。

    Args:
        command: 要执行的终端命令
        think: 执行此命令的思考过程

    Returns:
        命令执行结果
    """
    # 获取沙盒执行器
    executor = get_sandbox_executor()

    # 执行命令（确认逻辑由executor内部处理）
    result = executor.execute(command)

    if result.was_cancelled:
        return "命令执行被取消。"

    if result.success:
        output = result.stdout.strip() if result.stdout else ""
        return f"命令执行成功（耗时{result.execution_time:.2f}秒）。输出：\n{output}" if output else f"命令执行成功（耗时{result.execution_time:.2f}秒，无输出）。"
    else:
        error_output = result.stderr.strip() if result.stderr else ""
        return f"命令执行失败（返回码 {result.returncode}）。错误：\n{error_output}"


@tool
def get_current_working_directory() -> str:
    """获取当前工作目录的绝对路径。"""
    try:
        cwd = os.getcwd()
        return cwd
    except Exception as e:
        return f"获取当前工作目录时发生错误: {e}"


system_tools = [run_terminal_command, get_current_working_directory]
