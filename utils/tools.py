import os
import subprocess

# tools.py
class ToolSet:
    @staticmethod
    def read_file(file_path):
        """用于读取文件内容"""
        try:
            # 标准化路径，处理多余的斜杠/反斜杠
            normalized_path = os.path.normpath(file_path)
            with open(normalized_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"错误：找不到文件 '{normalized_path}'。请检查路径是否正确。"
        except OSError as e:
            # 更清晰地返回操作系统错误
            return f"错误：无法读取文件 '{normalized_path}'。系统报告: {e}"
        except Exception as e:
            return f"读取文件时发生未知错误: {e}"

    @staticmethod
    def write_to_file(file_path, content):
        """将指定内容写入指定文件"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content.replace("\\n", "\n"))
        return "写入成功"

    @staticmethod
    def run_terminal_command(command):
        """用于执行终端命令"""
        # 执行终端命令需要询问
        should_continue = input(f"\n⚠️  即将执行终端命令: {command}\n是否继续？（Y/N）: ")
        if should_continue.lower() != 'y':
            return "用户取消了终端命令的执行。"
        
        # 执行命令
        run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if run_result.returncode == 0:
            # 成功时，返回标准输出，如果为空则返回成功提示
            output = run_result.stdout.strip()
            return f"命令执行成功。输出：\n{output}" if output else "命令执行成功（无输出）。"
        else:
            # 失败时，返回错误信息
            error_output = run_result.stderr.strip()
            return f"命令执行失败（返回码 {run_result.returncode}）。错误输出：\n{error_output}"