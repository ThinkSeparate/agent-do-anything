from langchain.tools import BaseTool
from typing import Type, Dict, Any, Optional, Callable
import logging
from pydantic import PrivateAttr  # 添加PrivateAttr导入

# 获取一个专门的日志器来记录思考过程
think_logger = logging.getLogger("think_logger")
# 可以配置此日志器输出到文件或特定格式，这里使用基础配置
if not think_logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - [THINK] - %(message)s')
    handler.setFormatter(formatter)
    think_logger.addHandler(handler)
    think_logger.setLevel(logging.INFO)


def _think_processor(think_content: str, tool_name: str) -> None:
    """
    思考内容处理器。目前将思考内容记录到日志。
    未来可扩展为存储到数据库、发送到前端等。
    """
    print(think_content)
    if think_content and think_content.strip():
        think_logger.info(f"[Tool: {tool_name}] {think_content}")
    else:
        think_logger.warning(f"[Tool: {tool_name}] 模型未提供思考内容（think参数为空）。")


def wrap_tool_with_think(original_tool: BaseTool) -> BaseTool:
    """包装原始工具，返回带有think参数的版本"""
    return ToolWithThink(original_tool, _think_processor)


class ToolWithThink(BaseTool):
    """带有think参数的工具包装器"""
    
    # 使用PrivateAttr将属性标记为私有，不纳入Pydantic字段
    _original_tool: BaseTool = PrivateAttr()
    _think_processor: Callable[[str, str], None] = PrivateAttr()
    
    def __init__(self, original_tool: BaseTool, think_processor: Callable[[str, str], None]):
        # 构建新的参数模式
        from pydantic import create_model
        from inspect import signature
        
        # 获取原始工具的参数
        sig = signature(original_tool._run)
        fields = {"think": (str, ...)}  # 添加think参数
        
        # 添加原始工具的参数
        for param_name, param in sig.parameters.items():
            if param_name != 'self' and param_name != 'think':
                fields[param_name] = (param.annotation, param.default)
        
        # 创建新的参数模型
        args_schema = create_model(f"{original_tool.name}WithThinkArgs", **fields)
        
        # 先调用父类的__init__，初始化Pydantic模型
        super().__init__(
            name=original_tool.name,
            description=f"（带思考）{original_tool.description}",
            args_schema=args_schema,
        )
        
        # 父类初始化完成后，再设置私有属性
        self._original_tool = original_tool
        self._think_processor = think_processor
    
    def _run(self, think: str, **kwargs: Any) -> Any:
        """执行工具"""
        self._think_processor(think, self._original_tool.name)
        return self._original_tool._run(**kwargs)
    
    async def _arun(self, think: str, **kwargs: Any) -> Any:
        """异步执行工具"""
        self._think_processor(think, self._original_tool.name)
        return await self._original_tool._arun(**kwargs)