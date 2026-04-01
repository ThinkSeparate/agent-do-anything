# core/tool_manager.py
import inspect
import logging
from typing import Any, Dict, Callable

from utils.tools import ToolSet


class ToolManager:
    """工具管理器，负责工具的加载、验证和执行。"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("ToolManager 初始化开始", extra={'tag': 'TOOL_MANAGER_INIT'})
        
        # 动态加载工具
        tool_methods = [
            func for name, func in inspect.getmembers(ToolSet, predicate=inspect.isfunction)
            if not name.startswith('__')
        ]
        self.tools: Dict[str, Callable] = {func.__name__: func for func in tool_methods}
        
        self.logger.info(f"加载了 {len(self.tools)} 个工具: {', '.join(self.tools.keys())}",
                        extra={'tag': 'TOOL_MANAGER_INIT'})
        self.logger.info("ToolManager 初始化完成", extra={'tag': 'TOOL_MANAGER_INIT'})

    def get_tool_list(self) -> str:
        """生成工具列表的详细描述字符串。"""
        tool_descriptions = []
        for func in self.tools.values():
            name = func.__name__
            signature = str(inspect.signature(func))
            doc = inspect.getdoc(func) or "暂无描述"
            tool_descriptions.append(f"- {name}{signature}: {doc}")
        return "\n".join(tool_descriptions)

    def execute_tool(self, tool_name: str, args: list) -> Any:
        """
        执行指定的工具。
        
        Args:
            tool_name: 工具函数名
            args: 传递给工具的参数列表
            
        Returns:
            工具的执行结果
            
        Raises:
            KeyError: 当工具不存在时
            Exception: 工具执行过程中抛出的任何异常
        """
        self.logger.info(f"调用工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})
        
        if tool_name not in self.tools:
            error_msg = f"工具 '{tool_name}' 不存在。可用工具: {list(self.tools.keys())}"
            self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
            raise KeyError(error_msg)
        
        try:
            result = self.tools[tool_name](*args)
            self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})
            self.logger.debug(f"工具执行结果: {result}", extra={'tag': 'TOOL_RESULT'})
            return result
        except Exception as e:
            # 记录原始错误，但将异常向上抛出，由调用者决定如何处理
            self.logger.error(f"工具 '{tool_name}' 执行失败。参数: {args}。错误详情: {e}",
                            exc_info=True, extra={'tag': 'TOOL_ERROR'})
            raise