# tools/__init__.py
from tools._safety import configure_agent_output_root
from tools.file_tools import file_tools
from tools.system_tools import system_tools
from tools.network_tools import network_tools, make_http_request
from tools.office_tools import office_tools
from tools.interactive_tools import short_task_tools, long_task_tools
from tools.clarify_special_tools import clarify_special_tools
from tools.wrap_with_think import wrap_tool_with_think
from tools.planning_tools import planning_tools
from tools.clarify_special_tools import clarify_special_tools
from tools.integrated_compression_tool import invoke_context_compressor
from tools.compress_messages import compress_tools

# 更新 __all__
__all__ = [
    'configure_agent_output_root',
    'invoke_context_compressor',
    'get_clarify_tools',
    'get_react_tools',
    'get_plan_tools',  # 新增
    'get_all_tools',
    'make_http_request',
    'wrap_tool_with_think',
    'ToolRegistry',
]

# 基础工具（所有模式共用）
_base_tools = (
    file_tools + system_tools + network_tools +
    office_tools + clarify_special_tools +
    planning_tools + compress_tools
)

class ToolRegistry:
    """工具注册表，管理不同Agent的工具集"""
    
    def __init__(self):
        self._tools_by_name = {}
        self._agent_tool_sets = {}
    
    def register_agent_tools(self, agent_type: str, tool_names: list):
        """
        注册Agent可用的工具集
        
        Args:
            agent_type: Agent类型，如"clarify"、"react"
            tool_names: 允许使用的工具名称列表
        """
        # 从所有原始工具中筛选
        available_tools = []
        for tool_name in tool_names:
            if tool_name in self._tools_by_name:
                available_tools.append(self._tools_by_name[tool_name])
        
        # 包装工具
        wrapped_tools = [wrap_tool_with_think(tool) for tool in available_tools]
        self._agent_tool_sets[agent_type] = wrapped_tools
    
    def get_agent_tools(self, agent_type: str):
        """获取指定Agent的工具集"""
        return self._agent_tool_sets.get(agent_type, [])
    
    def register_all_tools(self):
        """注册所有原始工具"""
        for tool in _base_tools:
            self._tools_by_name[tool.name] = tool


# 创建全局工具注册表实例
_tool_registry = ToolRegistry()
_tool_registry.register_all_tools()

# 注册不同Agent的工具集
# 需求澄清Agent：只能使用通用交互工具和特定的澄清工具
_tool_registry.register_agent_tools(
    agent_type="clarify",
    tool_names=["ask_user", "submit_final_answer", "transfer_to_react"]
)



# 注册 Plan Agent 工具集
_plan_tool_names = (
    ["assign_task_to_react", "replan_tool", "submit_plan_report"] +
    ["ask_user", "submit_final_answer"]  # 可以问用户和提交答案
)
_tool_registry.register_agent_tools(
    agent_type="plan",
    tool_names=_plan_tool_names
)

# 新增便捷函数
def get_plan_tools():
    """获取规划Agent的工具集"""
    return _tool_registry.get_agent_tools("plan")

# 提供便捷的获取函数
def get_clarify_tools():
    """获取需求澄清Agent的工具集"""
    return _tool_registry.get_agent_tools("clarify")


def get_react_tools(task_mode: str = 'short'):
    """
    获取执行Agent（ReActAgent）的工具集

    Args:
        task_mode: 'short' 短任务模式（使用 submit_final_answer）
                  'long' 长任务模式（使用 wait_for_next_task）

    Returns:
        对应模式的工具列表
    """
    # 基础工具
    base_tool_names = (
        [tool.name for tool in file_tools] +
        [tool.name for tool in system_tools] +
        [tool.name for tool in network_tools] +
        [tool.name for tool in office_tools] +
        [tool.name for tool in compress_tools]
    )

    # 根据模式选择交互工具
    if task_mode == 'long':
        interactive_names = [tool.name for tool in long_task_tools]
    else:
        interactive_names = [tool.name for tool in short_task_tools]

    all_tool_names = base_tool_names + interactive_names

    # 从注册表获取工具并包装
    tools = []
    for name in all_tool_names:
        if name in _tool_registry._tools_by_name:
            tools.append(wrap_tool_with_think(_tool_registry._tools_by_name[name]))

    return tools


def get_all_tools():
    """获取所有工具（包装版）"""
    return [wrap_tool_with_think(tool) for tool in _base_tools]

# 构建工具名到包装后工具的映射
tools_by_name = {tool.name: tool for tool in _base_tools}