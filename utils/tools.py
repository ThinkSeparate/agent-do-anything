# utils/tools.py
import os
import subprocess

class ToolSet:
    @staticmethod
    def read_file(file_path):
        """用于读取文件内容"""
        try:
            normalized_path = os.path.normpath(file_path)
            with open(normalized_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 操作成功，将内容放入 'data'
            return {'operation_succeeded': True, 'data': content}
        except FileNotFoundError:
            # 操作失败，将错误信息放入 'data'，也可明确设置 'error'
            return {'operation_succeeded': False, 'data': f"错误：找不到文件 '{normalized_path}'。"}
        except OSError as e:
            return {'operation_succeeded': False, 'data': f"错误：无法读取文件 '{normalized_path}'。系统报告: {e}"}
        except Exception as e:
            return {'operation_succeeded': False, 'data': f"读取文件时发生未知错误: {e}"}

    @staticmethod
    def write_to_file(file_path, content):
        """将指定内容写入指定文件"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content.replace("\\n", "\n"))
            # 写入成功，返回成功消息
            return {'operation_succeeded': True, 'data': f"文件 '{file_path}' 写入成功。"}
        except Exception as e:
            # 写入失败，返回错误
            return {'operation_succeeded': False, 'data': f"写入文件 '{file_path}' 时发生错误: {e}"}

    @staticmethod
    def run_terminal_command(command):
        """用于执行终端命令"""
        should_continue = input(f"\n⚠️  即将执行终端命令: {command}\n是否继续？（Y/N）: ")
        if should_continue.lower() != 'y':
            # 用户取消，也是一种操作失败
            return {'operation_succeeded': False, 'data': "用户取消了终端命令的执行。"}
        
        run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        if run_result.returncode == 0:
            output = run_result.stdout.strip()
            result_data = f"命令执行成功。输出：\n{output}" if output else "命令执行成功（无输出）。"
            return {
                'operation_succeeded': True,
                'data': result_data,
                'returncode': run_result.returncode
            }
        else:
            error_output = run_result.stderr.strip()
            return {
                'operation_succeeded': False,
                'data': f"命令执行失败（返回码 {run_result.returncode}）。错误输出：\n{error_output}",
                'returncode': run_result.returncode
            }