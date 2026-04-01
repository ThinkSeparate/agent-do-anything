import ast
import inspect
import os
import re
import logging
import datetime
from logging.handlers import TimedRotatingFileHandler
from string import Template
from typing import List, Callable, Tuple
import json

import click
from dotenv import load_dotenv
from openai import OpenAI
import platform

from prompt_template import react_system_prompt_template


# 配置日志
def setup_logging(project_directory=None):
    """配置日志格式和级别，将INFO及以上输出到控制台，DEBUG及以上输出到文件"""

    # 1. 自定义 Formatter，确保所有记录都有 `tag` 属性
    class SafeTagFormatter(logging.Formatter):
        def format(self, record):
            if not hasattr(record, 'tag'):
                record.tag = 'EXTERNAL'
            return super().format(record)
    
    # 2. 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 记录器本身捕获所有级别
    
    # 清除旧的处理器，防止重复
    if root_logger.handlers:
        root_logger.handlers.clear()
    
    # 3. 创建并配置【控制台处理器】- 仅INFO及以上
    console_formatter = SafeTagFormatter(
        '%(asctime)s - %(levelname)s - [%(tag)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # 关键：控制台只显示INFO及以上
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 4. 创建并配置【文件处理器】- DEBUG及以上，格式更详细
    if project_directory:
        # 在项目目录下创建 logs 文件夹
        log_dir = os.path.join(project_directory, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # 【修改点】生成包含启动时间戳的日志文件名，格式示例：agent_20240401_143022.log
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f'agent_{timestamp}.log')
        
        # 文件格式可以包含更多调试信息，如文件名、行号
        file_formatter = SafeTagFormatter(
            '%(asctime)s - %(levelname)s - [%(tag)s] - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 【修改点】使用基本的 FileHandler，因为每次运行文件已唯一，无需按时间滚动
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # 关键：文件记录DEBUG及以上所有信息
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        logging.info(f"本次运行的日志文件：{log_file}", extra={'tag': 'LOG_INIT'})
    
    # 5. 可选：添加一个过滤器，为没有tag的记录设置默认值（双保险）
    class TagFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, 'tag'):
                record.tag = 'SYSTEM'
            return True
    root_logger.addFilter(TagFilter())


# 单独的工具类，存放所有工具方法
class ToolSet:
    @staticmethod
    def read_file(file_path):
        """用于读取文件内容"""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write_to_file(file_path, content):
        """将指定内容写入指定文件"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content.replace("\\n", "\n"))
        return "写入成功"

    @staticmethod
    def run_terminal_command(command):
        """用于执行终端命令"""
        import subprocess
        run_result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return "执行成功" if run_result.returncode == 0 else run_result.stderr


class ReActAgent:
    def __init__(self, project_directory: str):
        # 获取本类的日志器
        self.logger = logging.getLogger(__name__)
        
        # 记录代理初始化
        self.logger.info("ReActAgent 初始化开始", extra={'tag': 'AGENT_INIT'})
        
        tool_methods = [
            func for name, func in inspect.getmembers(ToolSet, predicate=inspect.isfunction)
            if not name.startswith('__')
        ]
        self.tools = {func.__name__: func for func in tool_methods}
        self.model = ReActAgent.get_env("MODEL_NAME")
        self.project_directory = project_directory
        self.client = OpenAI(
            base_url=ReActAgent.get_env("BASE_URL"), 
            api_key=ReActAgent.get_env("API_KEY"),
        )
        
        # 记录可用的工具
        self.logger.info(f"加载了 {len(self.tools)} 个工具: {', '.join(self.tools.keys())}", 
                        extra={'tag': 'AGENT_INIT'})
        self.logger.info("ReActAgent 初始化完成", extra={'tag': 'AGENT_INIT'})

    def run(self, user_input: str):
        # 记录用户输入
        self.logger.info(f"用户输入: {user_input}", extra={'tag': 'USER_INPUT'})
        
        messages = [
            {"role": "system", "content": self.render_system_prompt(react_system_prompt_template)},
            {"role": "user", "content": f"<question>{user_input}</question>"}
        ]

        while True:
            # 记录发送给模型的完整消息
            self._log_messages("发送给模型的消息", messages)
            
            # 请求模型
            self.logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})
            content = self.call_model(messages)
            self.logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})
            
            # 记录模型的完整响应内容
            self.logger.debug(f"模型原始响应:\n{content}", extra={'tag': 'MODEL_RAW'})

            # 检测 Thought
            thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
            if thought_match:
                thought = thought_match.group(1)
                self.logger.info(f"Thought: {thought}", extra={'tag': 'THOUGHT'})

            # 检测模型是否输出 Final Answer，如果是的话，直接返回
            if "<final_answer>" in content:
                final_answer = re.search(r"<final_answer>(.*?)</final_answer>", content, re.DOTALL)
                final_answer_text = final_answer.group(1)
                self.logger.info(f"模型输出最终答案", extra={'tag': 'FINAL_ANSWER'})
                self.logger.info(f"最终答案内容: {final_answer_text}", extra={'tag': 'FINAL_ANSWER'})
                return final_answer_text

            # 检测 Action
            action_match = re.search(r"<action>(.*?)</action>", content, re.DOTALL)
            if not action_match:
                error_msg = "模型未输出 <action> 标签"
                self.logger.error(error_msg, extra={'tag': 'ERROR'})
                raise RuntimeError(error_msg)
            
            action = action_match.group(1)
            tool_name, args = self.parse_action(action)

            self.logger.info(f"解析到工具调用: {tool_name}", extra={'tag': 'ACTION_PARSE'})
            self.logger.info(f"工具参数: {args}", extra={'tag': 'ACTION_PARSE'})
            
            # 只有终端命令才需要询问用户，其他的工具直接执行
            if tool_name == "run_terminal_command":
                self.logger.warning(f"即将执行终端命令: {args[0] if args else '无参数'}", 
                                  extra={'tag': 'TERMINAL_WARNING'})
                should_continue = input(f"\n⚠️  即将执行终端命令: {args[0] if args else '无参数'}\n是否继续？（Y/N）")
                if should_continue.lower() != 'y':
                    self.logger.warning("用户取消了终端命令执行", extra={'tag': 'USER_CANCEL'})
                    print("\n操作已取消。")
                    return "操作被用户取消"
            else:
                self.logger.info(f"执行工具: {tool_name}", extra={'tag': 'TOOL_EXECUTION'})

            try:
                observation = self.tools[tool_name](*args)
                self.logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})
                self.logger.debug(f"工具执行结果: {observation}", extra={'tag': 'TOOL_RESULT'})
            except Exception as e:
                error_msg = f"工具执行错误：{str(e)}"
                self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
                self.logger.error(f"错误工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_ERROR'})
                observation = f"工具执行错误：{str(e)}：工具“{tool_name}”不存在。请从可用工具列表中选择：{list(self.tools.keys())}。"
            
            obs_msg = f"<observation>{observation}</observation>"
            messages.append({"role": "user", "content": obs_msg})
            
            # 记录添加到消息历史中的观察结果
            self.logger.debug(f"添加到消息历史的观察: {observation[:200]}...", 
                            extra={'tag': 'OBSERVATION_ADDED'})

    def _log_messages(self, title: str, messages: list):
        """记录消息列表的辅助方法"""
        self.logger.info(f"=== {title} ===", extra={'tag': 'MESSAGES'})
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            # 截断过长的内容以便阅读
            content_preview = content[:300] + "..." if len(content) > 300 else content
            
            self.logger.info(f"[消息 {i}] 角色: {role}", extra={'tag': 'MESSAGES'})
            self.logger.debug(f"内容预览:\n{content_preview}", extra={'tag': 'MESSAGES_DETAIL'})
            
            # 如果是系统提示，记录完整内容到调试日志
            if role == 'system':
                self.logger.debug(f"系统提示完整内容:\n{content}", extra={'tag': 'SYSTEM_PROMPT'})
        
        self.logger.info(f"=== {title} 结束 ===", extra={'tag': 'MESSAGES'})

    def get_tool_list(self) -> str:
        """生成工具列表字符串，包含函数签名和简要说明"""
        tool_descriptions = []
        for func in self.tools.values():
            name = func.__name__
            signature = str(inspect.signature(func))
            doc = inspect.getdoc(func)
            tool_descriptions.append(f"- {name}{signature}: {doc}")
        return "\n".join(tool_descriptions)

    def render_system_prompt(self, system_prompt_template: str) -> str:
        """渲染系统提示模板，替换变量"""
        self.logger.debug("开始渲染系统提示模板", extra={'tag': 'PROMPT_RENDER'})
        
        tool_list = self.get_tool_list()
        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )
        
        result = Template(system_prompt_template).substitute(
            operating_system=self.get_operating_system_name(),
            tool_list=tool_list,
            file_list=file_list
        )
        
        self.logger.debug(f"系统提示渲染完成，长度: {len(result)} 字符", 
                         extra={'tag': 'PROMPT_RENDER'})
        return result

    @staticmethod
    def get_env(env_key) -> str:
        """Load the API key from an environment variable."""
        load_dotenv()
        api_key = os.getenv(env_key)
        if not api_key:
            error_msg = f"未找到 {env_key} 环境变量，请在 .env 文件中设置。"
            logging.error(error_msg, extra={'tag': 'ENV_ERROR'})
            raise ValueError(error_msg)
        
        # 安全地记录环境变量（隐藏敏感信息的部分）
        masked_key = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "***"
        logging.debug(f"已加载环境变量 {env_key}: {masked_key}", extra={'tag': 'ENV_LOAD'})
        return api_key

    def call_model(self, messages):
        self.logger.info("调用模型 API...", extra={'tag': 'API_CALL'})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            
            content = response.choices[0].message.content
            messages.append({"role": "assistant", "content": content})
            
            # 记录 API 调用统计信息
            self.logger.info(f"API 调用成功，模型: {self.model}", extra={'tag': 'API_SUCCESS'})
            if hasattr(response, 'usage'):
                usage = response.usage
                self.logger.info(f"Token 使用情况 - 提示: {usage.prompt_tokens}, "
                               f"完成: {usage.completion_tokens}, "
                               f"总计: {usage.total_tokens}", 
                               extra={'tag': 'API_USAGE'})
            
            return content
            
        except Exception as e:
            self.logger.error(f"API 调用失败: {str(e)}", extra={'tag': 'API_ERROR'})
            raise

    def parse_action(self, code_str: str) -> Tuple[str, List[str]]:
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
        """解析单个参数"""
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

    def get_operating_system_name(self):
        os_map = {
            "Darwin": "macOS",
            "Windows": "Windows",
            "Linux": "Linux"
        }
        
        system_name = platform.system()
        os_name = os_map.get(system_name, "Unknown")
        self.logger.debug(f"检测到操作系统: {system_name} -> {os_name}", extra={'tag': 'OS_DETECT'})
        return os_name


@click.command()
@click.argument('project_directory',
                type=click.Path(exists=True, file_okay=False, dir_okay=True))
def main(project_directory):
    project_dir = os.path.abspath(project_directory)

    # 关键修改：传递 project_dir 以启用文件日志
    setup_logging(project_dir)  # 修改了这一行
    
    # 记录程序开始
    logging.info(f"程序启动，项目目录: {project_dir}", extra={'tag': 'APP_START'})

    agent = ReActAgent(project_directory=project_dir)

    task = input("请输入任务：")

    logging.info("开始执行任务", extra={'tag': 'TASK_START'})
    final_answer = agent.run(task)
    logging.info("任务执行完成", extra={'tag': 'TASK_END'})

    print(f"\n\n✅ Final Answer：{final_answer}")
    logging.info(f"最终答案: {final_answer}", extra={'tag': 'FINAL_OUTPUT'})

if __name__ == "__main__":
    main()