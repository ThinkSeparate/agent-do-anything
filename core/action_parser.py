# core/action_parser.py
import re
import ast
import logging
from typing import Tuple, List


class ActionParser:
    """动作解析器，负责解析模型返回的 <action> 标签内容。"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse(self, code_str: str) -> Tuple[str, List]:
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
            # 移除外层引号并处理转义字符
            inner_str = arg_str[1:-1]
            # 处理常见的转义字符
            inner_str = inner_str.replace('\\"', '"').replace("\\'", "'")
            inner_str = inner_str.replace('\\n', '\n').replace('\\t', '\t')
            inner_str = inner_str.replace('\\r', '\r').replace('\\\\', '\\')
            return inner_str
        
        # 尝试使用 ast.literal_eval 解析其他类型
        try:
            return ast.literal_eval(arg_str)
        except (SyntaxError, ValueError):
            # 如果解析失败，返回原始字符串
            return arg_str