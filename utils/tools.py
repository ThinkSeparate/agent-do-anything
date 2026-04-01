import os

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
        import subprocess
        run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return "执行成功" if run_result.returncode == 0 else run_result.stderr