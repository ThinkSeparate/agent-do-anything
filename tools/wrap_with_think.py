from langchain.tools import BaseTool
from typing import Type, Dict, Any, Optional, Callable, get_type_hints, Union, get_origin, get_args
import logging
from pydantic import PrivateAttr, create_model
from inspect import signature, Parameter

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


def _build_args_fields(original_tool: BaseTool) -> dict:
    """从原始工具的args_schema直接复制字段定义，保持完整类型信息"""
    fields = {"think": (str, ...)}

    if hasattr(original_tool, 'args_schema') and original_tool.args_schema:
        # 直接复用原始Pydantic模型的model_fields，避免JSON schema往返转换丢失类型
        for field_name, field_info in original_tool.args_schema.model_fields.items():
            fields[field_name] = (field_info.annotation, field_info)
    else:
        # 回退：从_run函数签名提取
        try:
            sig = signature(original_tool._run)
            type_hints = get_type_hints(original_tool._run)
            for param_name, param in sig.parameters.items():
                if param_name not in ('self', 'kwargs', 'config'):
                    param_type = type_hints.get(param_name, str)
                    if param.default != Parameter.empty:
                        fields[param_name] = (param_type, param.default)
                    else:
                        fields[param_name] = (param_type, ...)
        except Exception:
            pass

    return fields


def wrap_tool_with_think(original_tool: BaseTool) -> BaseTool:
    """包装原始工具，返回带有think参数的版本，保持原始参数类型"""

    # 方案1：直接继承并重写
    class ToolWithThinkFixed(BaseTool):
        name: str = original_tool.name
        description: str = f"（带思考）{original_tool.description}"

        # 关键：正确构建参数模式
        class Config:
            arbitrary_types_allowed = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._original_tool = original_tool

        def _run(self, think: str, **kwargs: Any) -> Any:
            """执行工具，优先记录think内容"""
            # 记录思考过程
            if think and think.strip():
                print(f"[THINK - {self.name}]: {think}")
                think_logger.info(f"[Tool: {self.name}] {think}")

            # 调用原始工具的_run方法，传递config参数
            # BaseTool的_run方法需要config参数，但我们不需要在包装中处理它
            # 从kwargs中提取config（如果有的话）
            config = kwargs.pop('config', None)
            if config is not None:
                return self._original_tool._run(**kwargs, config=config)
            else:
                return self._original_tool._run(**kwargs)

        async def _arun(self, think: str, **kwargs: Any) -> Any:
            """异步执行工具"""
            if think and think.strip():
                print(f"[THINK - {self.name}]: {think}")
                think_logger.info(f"[Tool: {self.name}] {think}")

            # 处理config参数
            config = kwargs.pop('config', None)
            if config is not None:
                return await self._original_tool._arun(**kwargs, config=config)
            else:
                return await self._original_tool._arun(**kwargs)

    fields = _build_args_fields(original_tool)

    args_schema_model = create_model(
        f"{original_tool.name}Args",
        **fields
    )

    tool_instance = ToolWithThinkFixed(args_schema=args_schema_model)
    return tool_instance
