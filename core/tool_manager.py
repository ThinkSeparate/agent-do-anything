# core/tool_manager.py
import inspect
import logging
import re
import ast
from typing import Any, Dict, Callable, get_type_hints, Tuple, List, Union
from functools import wraps

from utils.tools import ToolSet


class ToolManager:
    """工具管理器，负责工具的加载、验证、解析和执行。"""

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

    def handle_action(self, action_str: str) -> Dict[str, Any]:
        """
        完整处理动作字符串：解析 -> 查找工具 -> 验证参数 -> 执行 -> 返回结构化结果

        Args:
            action_str: 动作字符串，如 `read_file("test.txt")`

        Returns:
            一个包含执行状态和数据的字典。
            格式: {
                'success': True,  # 或 False
                'data': '执行结果或错误信息字符串'
            }
        """
        self.logger.debug(f"处理动作字符串: {action_str}", extra={'tag': 'ACTION_HANDLE'})

        try:
            # 1. 解析动作字符串
            tool_name, args = self._parse_action(action_str)
        except ValueError as e:
            error_msg = f"动作解析失败: {e}"
            self.logger.error(error_msg, extra={'tag': 'ACTION_PARSE_ERROR'})
            # 返回结构化失败结果
            return {
                'success': False,
                'data': f"动作解析失败: {e}。请确保使用正确的函数调用语法，如：tool_name(arg1, arg2)。"
            }

        # 2. 查找并执行工具
        try:
            # execute_tool 成功时返回工具的执行结果
            result = self.execute_tool(tool_name, args)
            # 返回结构化成功结果
            return {
                'success': True,
                'data': str(result)  # 确保结果为字符串类型以便后续处理
            }
        except KeyError as e:
            # 工具不存在
            available = list(self.tools.keys())
            error_msg = f"工具“{tool_name}”不存在。请从可用工具列表中选择：{available}"
            self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
            return {
                'success': False,
                'data': error_msg
            }
        except (ValueError, TypeError) as e:
            # 参数数量或类型错误（通常由 _validate_arguments 或 execute_tool 内部抛出）
            error_msg = f"工具调用失败（参数错误）: {e}"
            self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION_ERROR'})
            return {
                'success': False,
                'data': error_msg
            }
        except Exception as e:
            # 其他执行期异常（工具函数内部异常）
            error_msg = f"执行工具 {tool_name} 时发生内部错误: {e}"
            self.logger.error(error_msg, exc_info=True, extra={'tag': 'TOOL_EXECUTION_ERROR'})
            return {
                'success': False,
                'data': error_msg
            }
    
    def _parse_action(self, code_str: str) -> Tuple[str, List]:
        """
        解析动作字符串，例如：`search_db("query")` -> ('search_db', ['query'])
        
        Args:
            code_str: 包含函数名和参数的字符串
            
        Returns:
            元组 (函数名, 参数列表)
            
        Raises:
            ValueError: 当字符串不符合预期格式时
        """
        self.logger.debug(f"解析动作字符串: {code_str}", extra={'tag': 'ACTION_PARSE'})
        
        match = re.match(r'(\w+)\((.*)\)', code_str, re.DOTALL)
        if not match:
            error_msg = f"无效的函数调用语法: {code_str}"
            self.logger.error(error_msg, extra={'tag': 'PARSE_ERROR'})
            raise ValueError("Invalid function call syntax")

        func_name = match.group(1)
        args_str = match.group(2).strip()

        # 手动解析参数，特别处理包含多行内容的字符串
        args = []
        current_arg = ""
        in_string = False
        string_char = None
        i = 0
        paren_depth = 0
        
        while i < len(args_str):
            char = args_str[i]
            
            if not in_string:
                if char in ['"', "'"]:
                    in_string = True
                    string_char = char
                    current_arg += char
                elif char == '(':
                    paren_depth += 1
                    current_arg += char
                elif char == ')':
                    paren_depth -= 1
                    current_arg += char
                elif char == ',' and paren_depth == 0:
                    # 遇到顶层逗号，结束当前参数
                    parsed_arg = self._parse_single_arg(current_arg.strip())
                    args.append(parsed_arg)
                    self.logger.debug(f"解析到参数: {parsed_arg}", extra={'tag': 'ARG_PARSE'})
                    current_arg = ""
                else:
                    current_arg += char
            else:
                current_arg += char
                if char == string_char and (i == 0 or args_str[i-1] != '\\'):
                    in_string = False
                    string_char = None
            
            i += 1
        
        # 添加最后一个参数
        if current_arg.strip():
            parsed_arg = self._parse_single_arg(current_arg.strip())
            args.append(parsed_arg)
            self.logger.debug(f"解析到参数: {parsed_arg}", extra={'tag': 'ARG_PARSE'})
        
        self.logger.info(f"解析完成 - 函数: {func_name}, 参数数量: {len(args)}", 
                        extra={'tag': 'ACTION_PARSE'})
        return func_name, args
    
    def _parse_single_arg(self, arg_str: str):
        """解析单个参数字符串为Python对象。"""
        arg_str = arg_str.strip()
        
        # 如果是字符串字面量
        if (arg_str.startswith('"') and arg_str.endswith('"')) or \
           (arg_str.startswith("'") and arg_str.endswith("'")):
            # 移除外层引号
            inner_str = arg_str[1:-1]
            
            # >>>>>>>> 方案一：新增路径反斜杠保护逻辑 <<<<<<<<
            import re
            # 定义占位符，用于临时替换需要保护的反斜杠
            BACKSLASH_PLACEHOLDER = "@@BSLASH@@"
            
            # 匹配模式：一个反斜杠后跟一个“非特殊转义字符”
            # 在Python字符串中，合法的单字符转义序列包括：\n, \t, \r, \\, \", \'
            # 此正则匹配一个反斜杠，后跟一个不在 [nrt\\'"] 中的字符。
            # 这可以捕获像 \w, \s, \u (在路径中应是字面量) 这样的序列。
            def protect_backslash(match_obj):
                # 将匹配到的整个模式（如 \w）替换为 占位符+字母
                return BACKSLASH_PLACEHOLDER + match_obj.group(1)
            
            pattern = r'\\([^\\ntr\'\"])'
            inner_str = re.sub(pattern, protect_backslash, inner_str)
            # <<<<<<<< 保护逻辑结束 <<<<<<<<
            
            # 原有的处理常见转义字符的逻辑保持不变
            inner_str = inner_str.replace('\\"', '"').replace("\\'", "'")
            inner_str = inner_str.replace('\\n', '\n').replace('\\t', '\t')
            inner_str = inner_str.replace('\\r', '\r').replace('\\\\', '\\')
            
            # >>>>>>>> 方案一：恢复被保护的字符 <<<<<<<<
            # 将占位符替换回单个反斜杠
            inner_str = inner_str.replace(BACKSLASH_PLACEHOLDER, '\\')
            # <<<<<<<< 恢复逻辑结束 <<<<<<<<
            
            return inner_str
        
        # 尝试使用 ast.literal_eval 解析其他类型
        try:
            return ast.literal_eval(arg_str)
        except (SyntaxError, ValueError):
            # 如果解析失败，返回原始字符串
            return arg_str
    
    # 以下原有方法保持不变，只做简单标注
    def get_tool_list(self) -> str:
        """生成工具列表的详细描述字符串。"""
        # ... 保持原有实现不变 ...
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
                
                # 处理 Union 类型
                if hasattr(expected_type, '__origin__') and expected_type.__origin__ is Union:
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
            error_msg = (f"工具 '{tool_name}' 参数验证失败。参数: {args}。"
                        f"函数签名: {tool_info['signature']}。错误: {e}")
            self.logger.error(error_msg, extra={'tag': 'ARG_VALIDATION_ERROR'})
            raise
        except Exception as e:
            error_msg = f"工具 '{tool_name}' 执行失败。参数: {args}。错误详情: {e}"
            self.logger.error(error_msg, exc_info=True, extra={'tag': 'TOOL_ERROR'})
            raise