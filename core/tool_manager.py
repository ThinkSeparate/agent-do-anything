# core/tool_manager.py
import inspect
import logging
from typing import Any, Dict, Callable, get_type_hints
from functools import wraps

from utils.tools import ToolSet


class ToolManager:
    """工具管理器，负责工具的加载、验证和执行。"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("ToolManager 初始化开始", extra={'tag': 'TOOL_MANAGER_INIT'})
        
        # 动态加载工具，并获取函数的签名和类型提示
        self.tools: Dict[str, Dict] = {}
        for name, func in inspect.getmembers(ToolSet, predicate=inspect.isfunction):
            if not name.startswith('__'):
                # 获取函数的完整元数据
                signature = inspect.signature(func)
                type_hints = get_type_hints(func)
                doc = inspect.getdoc(func) or "暂无描述"
                
                self.tools[name] = {
                    'function': func,
                    'signature': signature,
                    'type_hints': type_hints,
                    'doc': doc,
                    'params': list(signature.parameters.keys())
                }
        
        tool_names = ', '.join(self.tools.keys())
        self.logger.info(f"加载了 {len(self.tools)} 个工具: {tool_names}",
                        extra={'tag': 'TOOL_MANAGER_INIT'})
        self.logger.info("ToolManager 初始化完成", extra={'tag': 'TOOL_MANAGER_INIT'})

    def get_tool_list(self) -> str:
        """生成工具列表的详细描述字符串。"""
        tool_descriptions = []
        for name, tool_info in self.tools.items():
            sig_str = str(tool_info['signature'])
            doc = tool_info['doc']
            tool_descriptions.append(f"- {name}{sig_str}: {doc}")
        return "\n".join(tool_descriptions)
    
    def _validate_arguments(self, tool_name: str, tool_info: Dict, args: list) -> None:
        """
        验证工具参数的数量和类型。
        
        Args:
            tool_name: 工具名称
            tool_info: 工具信息字典
            args: 传入的参数列表
            
        Raises:
            TypeError: 参数类型不匹配
            ValueError: 参数数量不正确
        """
        signature = tool_info['signature']
        params = list(signature.parameters.items())
        
        # 1. 验证参数数量
        required_params = []
        optional_params = []
        
        for param_name, param in params:
            if param_name == 'self':
                continue
            if param.default == inspect.Parameter.empty:
                required_params.append(param_name)
            else:
                optional_params.append(param_name)
        
        min_args = len(required_params)
        max_args = len(required_params) + len(optional_params)
        
        if len(args) < min_args:
            error_msg = (f"工具 '{tool_name}' 需要至少 {min_args} 个参数，"
                        f"但只提供了 {len(args)} 个。")
            self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION'})
            raise ValueError(error_msg)
        
        if len(args) > max_args:
            error_msg = (f"工具 '{tool_name}' 最多接受 {max_args} 个参数，"
                        f"但提供了 {len(args)} 个。")
            self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION'})
            raise ValueError(error_msg)
        
        # 2. 验证参数类型（如果提供了类型注解）
        type_hints = tool_info['type_hints']
        
        for i, (arg_value, (param_name, param)) in enumerate(zip(args, params)):
            if param_name == 'self':
                continue
                
            if param_name in type_hints:
                expected_type = type_hints[param_name]
                
                # 跳过 Any 类型和 None
                if expected_type == Any or expected_type is type(None):
                    continue
                
                # 处理 Union 类型（如 Optional[str] 实际上是 Union[str, None]）
                if hasattr(expected_type, '__origin__') and expected_type.__origin__ is Union:
                    # 检查是否匹配 Union 中的任意类型
                    union_types = expected_type.__args__
                    if not any(self._check_type(arg_value, t) for t in union_types if t is not type(None)):
                        error_msg = (f"工具 '{tool_name}' 的参数 '{param_name}' 类型不匹配。"
                                    f"期望类型: {expected_type}，实际类型: {type(arg_value)}")
                        self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION'})
                        raise TypeError(error_msg)
                elif not self._check_type(arg_value, expected_type):
                    error_msg = (f"工具 '{tool_name}' 的参数 '{param_name}' 类型不匹配。"
                                f"期望类型: {expected_type}，实际类型: {type(arg_value)}")
                    self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION'})
                    raise TypeError(error_msg)
        
        self.logger.debug(f"工具 '{tool_name}' 参数验证通过: {args}", 
                         extra={'tag': 'ARG_VALIDATION'})
    
    def _check_type(self, value: Any, expected_type: type) -> bool:
        """检查值是否符合期望类型（支持泛型）"""
        # 处理 List, Dict 等泛型
        if hasattr(expected_type, '__origin__'):
            origin = expected_type.__origin__
            
            if origin is list:
                if not isinstance(value, list):
                    return False
                # 检查列表元素类型
                if expected_type.__args__:
                    elem_type = expected_type.__args__[0]
                    return all(self._check_type(item, elem_type) for item in value)
                return True
            
            elif origin is dict:
                if not isinstance(value, dict):
                    return False
                # 检查字典键值类型
                if expected_type.__args__ and len(expected_type.__args__) == 2:
                    key_type, val_type = expected_type.__args__
                    return all(
                        self._check_type(k, key_type) and self._check_type(v, val_type)
                        for k, v in value.items()
                    )
                return True
            
            # 其他泛型暂时不深入检查
            return isinstance(value, origin)
        
        # 基本类型检查
        if expected_type == Any:
            return True
        
        # 处理 Optional 类型（实际上在 Union 中处理）
        return isinstance(value, expected_type)

    def execute_tool(self, tool_name: str, args: list) -> Any:
        """
        执行指定的工具，包含参数验证。
        
        Args:
            tool_name: 工具函数名
            args: 传递给工具的参数列表
            
        Returns:
            工具的执行结果
            
        Raises:
            KeyError: 当工具不存在时
            ValueError: 参数数量不正确时
            TypeError: 参数类型不匹配时
            Exception: 工具执行过程中抛出的任何异常
        """
        self.logger.info(f"调用工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})
        
        if tool_name not in self.tools:
            error_msg = f"工具 '{tool_name}' 不存在。可用工具: {list(self.tools.keys())}"
            self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
            raise KeyError(error_msg)
        
        tool_info = self.tools[tool_name]
        
        try:
            # 参数验证
            self._validate_arguments(tool_name, tool_info, args)
            
            # 执行工具
            result = tool_info['function'](*args)
            self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})
            self.logger.debug(f"工具执行结果: {result}", extra={'tag': 'TOOL_RESULT'})
            return result
        except (ValueError, TypeError) as e:
            # 参数验证错误，提供更详细的错误信息
            error_msg = (f"工具 '{tool_name}' 参数验证失败。参数: {args}。"
                        f"函数签名: {tool_info['signature']}。错误: {e}")
            self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION_ERROR'})
            raise
        except Exception as e:
            # 工具执行错误
            error_msg = f"工具 '{tool_name}' 执行失败。参数: {args}。错误详情: {e}"
            self.logger.error(error_msg, exc_info=True, extra={'tag': 'TOOL_ERROR'})
            raise