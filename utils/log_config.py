# log_config.py
import os
import logging
import datetime
from logging import Filter

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
        # 此Handler使用自己的格式化器，格式简单
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        # 在写入前，确保消息格式符合设计要求的“块”样式
        if record.tag == 'CONV_SEND':
            formatted_message = self._format_conv_block("发送消息", record.message)
        elif record.tag == 'CONV_RECV':
            formatted_message = self._format_conv_block("模型回复", record.message)
        else:
            formatted_message = record.message  # 理论上不会走到这里
        
        # 临时替换原始消息，然后调用父类emit
        original_msg = record.msg
        record.msg = formatted_message
        super().emit(record)
        record.msg = original_msg  # 恢复原始消息

    @staticmethod
    def _format_conv_block(title, content):
        """将对话内容格式化为带标题的分隔块。"""
        separator = "=" * 30
        return f"{separator} {title} {separator}\n{content}\n{separator} {title} {separator}\n"


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

# 为根记录器添加默认标签过滤器
root_logger = logging.getLogger()
root_logger.addFilter(DefaultTagFilter())