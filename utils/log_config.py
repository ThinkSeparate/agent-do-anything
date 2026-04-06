# log_config.py
import os
import logging
import datetime
import json
from logging import Filter
from langchain.messages import SystemMessage, HumanMessage, AIMessage

def setup_logging(project_directory=None):
    """
    配置三层日志系统。
    1. ConsoleHandler: INFO+, 固定宽度对齐格式。
    2. FileHandler: DEBUG+, 固定宽度对齐+文件名行号。
    3. ConvHandler: 仅处理CONV_SEND和CONV_RECV的独立对话日志。
    """
    # 1. 获取根日志记录器，并设置其捕获所有级别的日志
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 清除旧的处理器，防止重复
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 2. 创建并配置【第一层：控制台处理器 (ConsoleHandler)】
    console_formatter = AlignedFormatter(
        fmt='%(asctime)s  %(levelname)-8s  %(tag)-15s  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # INFO级别及以上
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 3. 创建并配置【第二层：详细日志处理器 (FileHandler)】
    if project_directory:
        log_dir = os.path.join(project_directory, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        agent_log_file = os.path.join(log_dir, f'agent_{timestamp}.log')
        
        file_formatter = AlignedFormatter(
            fmt='%(asctime)s  %(levelname)-8s  %(tag)-15s  %(message)-40s  %(filename)s:%(lineno)d',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler = logging.FileHandler(agent_log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # DEBUG级别及以上
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # 4. 创建并配置【第三层：通信日志处理器 (ConvHandler)】
        conv_log_file = os.path.join(log_dir, f'conv_{timestamp}.log')
        conv_handler = ConvHandler(conv_log_file)
        conv_handler.setLevel(logging.DEBUG)  # 处理DEBUG及以上，但由过滤器控制实际内容
        root_logger.addHandler(conv_handler)
        
        # 记录日志初始化信息
        root_logger.info("日志系统初始化完成。", extra={'tag': 'LOG_INIT'})
        root_logger.info(f"详细日志文件: {agent_log_file}", extra={'tag': 'LOG_INIT'})
        root_logger.info(f"通信日志文件: {conv_log_file}", extra={'tag': 'LOG_INIT'})


class AlignedFormatter(logging.Formatter):
    """自定义格式化器，用于生成固定宽度对齐的日志行。"""
    def format(self, record):
        # 确保所有记录都有 `tag` 属性
        if not hasattr(record, 'tag'):
            record.tag = 'EXTERNAL'
        return super().format(record)


class ConvHandler(logging.FileHandler):
    """专用于记录对话的处理器。"""
    def __init__(self, filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, encoding='utf-8')
        # 添加过滤器，只允许 CONV_SEND 和 CONV_RECV 通过
        self.addFilter(ConvFilter())
        # 此Handler使用自己的格式化器
        self.setFormatter(ConvFormatter())

    def emit(self, record):
        # 调用父类的emit，使用ConvFormatter进行格式化
        super().emit(record)


class ConvFormatter(logging.Formatter):
    """专用于对话日志的格式化器"""
    def format(self, record):
        # 根据标签类型添加不同的分隔块
        if record.tag == 'CONV_SEND':
            # 格式化消息对象
            formatted_content = format_messages_for_log(record.msg)
            return self._format_conv_block("发送消息", formatted_content)
        elif record.tag == 'CONV_RECV':
            # 格式化响应对象
            formatted_content = get_response_content(record.msg)
            return self._format_conv_block("模型回复", formatted_content)
        else:
            return record.msg  # 理论上不会走到这里，因为有ConvFilter

    @staticmethod
    def _format_conv_block(title, content):
        """将对话内容格式化为带标题的分隔块。"""
        separator = "=" * 30
        return f"{separator} {title} {separator}\n{content}\n\n"


class ConvFilter(Filter):
    """过滤器，只允许 CONV_SEND 和 CONV_RECV 标签的日志通过。"""
    def filter(self, record):
        return hasattr(record, 'tag') and record.tag in ('CONV_SEND', 'CONV_RECV')


# 可选：全局过滤器，为所有没有tag的记录设置默认值，确保兼容性
class DefaultTagFilter(Filter):
    def filter(self, record):
        if not hasattr(record, 'tag'):
            record.tag = 'SYSTEM'
        return True


def format_messages_for_log(messages):
    """
    将消息列表格式化为通信日志中易读的字符串。
    格式：
        [序号] 角色类型
        内容...
    
    Args:
        messages: 消息对象列表
    
    Returns:
        str: 格式化后的字符串
    """
    formatted_lines = []
    for i, msg in enumerate(messages, 1):
        # 确定角色类型
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, HumanMessage):
            role = "human"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            role = str(type(msg).__name__)
        
        # 获取内容
        content = msg.content if hasattr(msg, 'content') else str(msg)
        formatted_lines.append(f"[{i}] {role}\n{content}\n")
    
    return "".join(formatted_lines)


def get_response_content(response):
    """
    安全地从模型响应对象中提取内容文本。
    尝试从多个常见属性中获取，避免因属性名为空导致通信日志记录为空。

    Args:
        response: 模型调用返回的响应对象。

    Returns:
        str: 提取到的内容，如果都为空则返回提示字符串。
    """
    import json
    # 优先级1: 直接获取 content 属性
    if hasattr(response, 'content') and response.content:
        return response.content
    
    # 优先级2: 尝试从 'text' 等属性获取 (兼容其他接口)
    if hasattr(response, 'text') and response.text:
        return response.text
    
    # 优先级3: 尝试获取首个 AIMessage 块的内容
    if hasattr(response, 'message') and hasattr(response.message, 'content'):
        return response.message.content
    
    # 优先级4: 如果是字典类结构，尝试获取 'text' 或 'content' 键
    if isinstance(response, dict):
        # 如果是字典，尝试美化为多行JSON
        try:
            # 尝试获取'text'或'content'键值作为主要内容
            main_content = response.get('text') or response.get('content')
            if main_content:
                result = main_content + "\n\n"
            else:
                result = ""

            # 美化整个字典并附加
            formatted_dict = json.dumps(response, ensure_ascii=False, indent=2)
            return result + formatted_dict
        except (TypeError, ValueError):
            # 如果无法序列化为JSON，则回退到字符串表示
            pass
    
    # 最终回退：转换为字符串，并尝试美化结构
    try:
        # 尝试将响应对象转换为字典（适用于包含__dict__属性的对象）
        if hasattr(response, '__dict__'):
            # 转换为字典并美化
            response_dict = response.__dict__
            formatted_dict = json.dumps(response_dict, ensure_ascii=False, indent=2)
            return formatted_dict
        else:
            # 尝试直接转换为字典（如果已经是类字典结构）
            response_dict = dict(response) if hasattr(response, '__iter__') else str(response)
            if isinstance(response_dict, dict):
                formatted_dict = json.dumps(response_dict, ensure_ascii=False, indent=2)
                return formatted_dict
            else:
                # 如果不是字典结构，则转换为字符串
                content = str(response) if response is not None else ''
                return content if content else '[模型回复内容为空或无法解析]'
    except Exception:
        # 如果所有转换都失败，返回字符串表示
        content = str(response) if response is not None else ''
        return content if content else '[模型回复内容为空或无法解析]'


# 为根记录器添加默认标签过滤器
root_logger = logging.getLogger()
root_logger.addFilter(DefaultTagFilter())