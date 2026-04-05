# tools/system_tools.py
import os
import subprocess
from langchain_core.tools import tool


@tool
def run_terminal_command(command: str) -> str:
    """执行终端命令。"""
    should_continue = input(f"\n⚠️  即将执行终端命令: {command}\n是否继续？（Y/N）: ")
    if should_continue.lower() != 'y':
        return "用户取消了终端命令的执行。"

    run_result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if run_result.returncode == 0:
        output = run_result.stdout.strip()
        return f"命令执行成功。输出：\n{output}" if output else "命令执行成功（无输出）。"
    else:
        error_output = run_result.stderr.strip()
        return f"命令执行失败（返回码 {run_result.returncode}）。错误输出：\n{error_output}"


@tool
def get_current_working_directory() -> str:
    """获取当前工作目录的绝对路径。"""
    try:
        cwd = os.getcwd()
        return cwd
    except Exception as e:
        return f"获取当前工作目录时发生错误: {e}"


system_tools = [run_terminal_command, get_current_working_directory]
