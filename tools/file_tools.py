# tools/file_tools.py
import os
from langchain_core.tools import tool
from tools._safety import get_agent_output_root


@tool
def read_file(file_path: str) -> str:
    """读取文件内容。"""
    try:
        normalized_path = os.path.normpath(file_path)
        with open(normalized_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return f"错误：找不到文件 '{normalized_path}'。"
    except OSError as e:
        return f"错误：无法读取文件 '{normalized_path}'。系统报告: {e}"
    except Exception as e:
        return f"读取文件时发生未知错误: {e}"


@tool
def write_to_file(file_path: str, content: str) -> str:
    """将指定内容写入指定文件。"""
    # 安全检查
    agent_output_root = get_agent_output_root()
    if agent_output_root is not None:
        try:
            target_abs_path = os.path.abspath(file_path)
            agent_output_root_abs = os.path.abspath(agent_output_root)
        except Exception:
            target_abs_path = file_path
            agent_output_root_abs = agent_output_root

        is_safe_path = False
        try:
            common_path = os.path.commonpath([agent_output_root_abs, target_abs_path])
            is_safe_path = os.path.commonpath([agent_output_root_abs]) == common_path
        except (ValueError, TypeError):
            is_safe_path = False

        if not is_safe_path:
            should_continue = input(f"\n⚠️  即将向: {target_abs_path} 目录写入文件\n是否继续？（Y/N）: ")
            if should_continue.lower() != 'y':
                return "用户取消了文件写入操作。"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content.replace("\\n", "\n"))
        return f"文件 '{file_path}' 写入成功。"
    except Exception as e:
        return f"写入文件 '{file_path}' 时发生错误: {e}"


@tool
def list_directory(directory_path: str) -> str:
    """列出指定目录下的所有文件和子目录。"""
    # 安全检查
    agent_output_root = get_agent_output_root()
    if agent_output_root is not None:
        try:
            target_abs = os.path.abspath(directory_path)
            root_abs = os.path.abspath(agent_output_root)
            if not target_abs.startswith(root_abs):
                return f"出于安全考虑，仅允许列出安全目录 '{agent_output_root}' 下的路径。请求路径：'{directory_path}'"
        except Exception:
            return f"无法解析路径：'{directory_path}'。"

    try:
        if not os.path.exists(directory_path):
            return f"错误：目录 '{directory_path}' 不存在。"
        if not os.path.isdir(directory_path):
            return f"错误：路径 '{directory_path}' 不是一个目录。"

        entries = os.listdir(directory_path)
        files = []
        dirs = []
        for entry in entries:
            full_path = os.path.join(directory_path, entry)
            if os.path.isdir(full_path):
                dirs.append(entry + "/")
            else:
                files.append(entry)

        dirs.sort()
        files.sort()
        all_entries = dirs + files
        result_str = f"目录 '{directory_path}' 的内容 ({len(all_entries)} 个项目):\n"
        result_str += "\n".join(all_entries) if all_entries else "（空目录）"
        return result_str

    except PermissionError:
        return f"错误：没有权限读取目录 '{directory_path}'。"
    except Exception as e:
        return f"列举目录时发生错误: {e}"


@tool
def create_directory(directory_path: str) -> str:
    """创建新目录（包括必要的父目录）。"""
    # 安全检查
    agent_output_root = get_agent_output_root()
    if agent_output_root is not None:
        try:
            target_abs = os.path.abspath(directory_path)
            root_abs = os.path.abspath(agent_output_root)
            if not target_abs.startswith(root_abs):
                return f"出于安全考虑，仅允许在安全目录 '{agent_output_root}' 下创建子目录。请求路径：'{directory_path}'"
        except Exception:
            return f"无法解析路径：'{directory_path}'。"

    try:
        if os.path.exists(directory_path):
            if os.path.isdir(directory_path):
                return f"目录 '{directory_path}' 已存在。"
            else:
                return f"错误：路径 '{directory_path}' 已存在，但不是目录。"

        os.makedirs(directory_path, exist_ok=True)
        return f"目录 '{directory_path}' 创建成功。"

    except PermissionError:
        return f"错误：没有权限在 '{directory_path}' 创建目录。"
    except Exception as e:
        return f"创建目录时发生错误: {e}"


@tool
def file_exists(file_path: str) -> str:
    """检查文件或目录是否存在，并返回其类型。"""
    try:
        if not os.path.exists(file_path):
            return f"路径 '{file_path}' 不存在。"
        elif os.path.isfile(file_path):
            size = os.path.getsize(file_path)
            return f"路径 '{file_path}' 存在，它是一个文件（大小: {size} 字节）。"
        elif os.path.isdir(file_path):
            return f"路径 '{file_path}' 存在，它是一个目录。"
        else:
            return f"路径 '{file_path}' 存在，但既不是文件也不是目录（可能是特殊文件）。"
    except Exception as e:
        return f"检查路径时发生错误: {e}"


@tool
def move_within_output(source_path: str, destination_path: str) -> str:
    """在 agent-output 目录内移动文件或目录。源路径和目标路径都必须在 agent-output 目录下，否则报错。"""
    agent_output_root = get_agent_output_root()

    # 如果没有配置安全目录，则禁止移动操作
    if agent_output_root is None:
        return "错误：未配置 agent-output 目录，无法执行移动操作。"

    try:
        source_abs = os.path.abspath(source_path)
        dest_abs = os.path.abspath(destination_path)
        root_abs = os.path.abspath(agent_output_root)
    except Exception as e:
        return f"错误：无法解析路径。系统报告: {e}"

    # 检查源路径是否在 agent-output 目录下
    source_in_safe_dir = False
    try:
        source_in_safe_dir = source_abs.startswith(root_abs)
    except (ValueError, TypeError):
        source_in_safe_dir = False

    # 检查目标路径是否在 agent-output 目录下
    dest_in_safe_dir = False
    try:
        dest_in_safe_dir = dest_abs.startswith(root_abs)
    except (ValueError, TypeError):
        dest_in_safe_dir = False

    # 如果任一路径不在安全目录下，返回错误
    if not source_in_safe_dir:
        return f"错误：源路径 '{source_path}' 不在 agent-output 目录 '{agent_output_root}' 下，移动操作被拒绝。"

    if not dest_in_safe_dir:
        return f"错误：目标路径 '{destination_path}' 不在 agent-output 目录 '{agent_output_root}' 下，移动操作被拒绝。"

    # 检查源路径是否存在
    if not os.path.exists(source_abs):
        return f"错误：源路径 '{source_path}' 不存在。"

    # 执行移动操作
    try:
        # 确保目标目录存在
        dest_parent = os.path.dirname(dest_abs)
        if dest_parent and not os.path.exists(dest_parent):
            os.makedirs(dest_parent, exist_ok=True)

        import shutil
        shutil.move(source_abs, dest_abs)

        if os.path.isdir(dest_abs):
            return f"目录 '{source_path}' 已成功移动到 '{destination_path}'。"
        else:
            return f"文件 '{source_path}' 已成功移动到 '{destination_path}'。"

    except PermissionError:
        return f"错误：没有权限移动 '{source_path}' 到 '{destination_path}'。"
    except Exception as e:
        return f"移动文件时发生错误: {e}"


file_tools = [read_file, write_to_file, list_directory, create_directory, file_exists, move_within_output]
