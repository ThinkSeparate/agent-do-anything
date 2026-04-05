# tools/__init__.py
from tools._safety import configure_agent_output_root
from tools.file_tools import file_tools
from tools.system_tools import system_tools
from tools.network_tools import network_tools
from tools.office_tools import office_tools
from tools.interactive_tools import interactive_tools

__all__ = [
    'configure_agent_output_root',
    'all_tools',
    'tools_by_name',
]

all_tools = file_tools + system_tools + network_tools + office_tools + interactive_tools
tools_by_name = {tool.name: tool for tool in all_tools}
