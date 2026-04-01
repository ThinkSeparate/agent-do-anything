# log_config.py
import os
import logging
import datetime

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
        
        # 生成包含启动时间戳的日志文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f'agent_{timestamp}.log')
        
        # 文件格式可以包含更多调试信息，如文件名、行号
        file_formatter = SafeTagFormatter(
            '%(asctime)s - %(levelname)s - [%(tag)s] - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 使用基本的 FileHandler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
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