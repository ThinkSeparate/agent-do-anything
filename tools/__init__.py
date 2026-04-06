# tools/__init__.py
from tools._safety import configure_agent_output_root
from tools.file_tools import file_tools
from tools.system_tools import system_tools
from tools.network_tools import network_tools
from tools.office_tools import office_tools
from tools.interactive_tools import interactive_tools

# 新增导入
from tools.wrap_with_think import wrap_tool_with_think

__all__ = [
    'configure_agent_output_root',
    'all_tools',
    'tools_by_name',
    'wrap_tool_with_think',  # 导出包装函数
]

# 原始工具列表
all_tools = file_tools + system_tools + network_tools + office_tools + interactive_tools

# 包装所有工具，为每个工具添加 think 参数
all_tools_with_think = [wrap_tool_with_think(tool) for tool in all_tools]

# 构建工具名到包装后工具的映射
tools_by_name = {tool.name: tool for tool in all_tools}