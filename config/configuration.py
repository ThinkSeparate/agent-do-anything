# config/configuration.py
import os
from typing import Any, Optional
import yaml  # 需要安装: pip install pyyaml
from pathlib import Path
import logging

class YAMLConfig:
    """纯YAML配置管理器，单例模式"""
    
    _instance = None
    _config_data = None
    _config_path = None
    
    def __new__(cls, config_path: str = 'config.yaml'):
        if cls._instance is None:
            cls._instance = super(YAMLConfig, cls).__new__(cls)
            # 初始化时确定配置路径
            cls._config_path = Path(config_path)
        return cls._instance
    
    def __init__(self, config_path: str = 'config.yaml'):
        # 防止__init__在已存在实例时重复运行
        if not hasattr(self, '_initialized'):
            self.logger = logging.getLogger(__name__)
            self._initialized = True
            # 注意：加载动作不在__init__中自动执行，由显式load()调用控制
    
    def load(self, required_keys: Optional[list] = None) -> None:
        """
        加载并解析YAML配置文件。
        
        Args:
            required_keys: 必需配置项的路径列表，例如 ['model.api_key', 'database.host']
        """
        if not self._config_path.exists():
            error_msg = f"配置文件不存在: {self._config_path.absolute()}"
            self.logger.critical(error_msg, extra={'tag': 'CONFIG_ERROR'})
            raise FileNotFoundError(error_msg)
        
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                self._config_data = yaml.safe_load(f) or {}
            self.logger.info(f"YAML配置文件加载成功: {self._config_path}", extra={'tag': 'CONFIG_LOAD'})
        except yaml.YAMLError as e:
            error_msg = f"配置文件YAML格式错误: {e}"
            self.logger.critical(error_msg, extra={'tag': 'CONFIG_ERROR'})
            raise ValueError(error_msg)
        
        # 验证必需配置项
        if required_keys:
            self._validate_required_keys(required_keys)
    
    def _validate_required_keys(self, required_keys: list) -> None:
        """验证必需的配置项路径是否存在"""
        missing_keys = []
        for key_path in required_keys:
            if self._get_nested_value(key_path) is None:
                missing_keys.append(key_path)
        
        if missing_keys:
            error_msg = f"配置文件中缺少必需的配置项: {', '.join(missing_keys)}"
            self.logger.critical(error_msg, extra={'tag': 'CONFIG_ERROR'})
            raise ValueError(error_msg)
    
    def _get_nested_value(self, key_path: str) -> Any:
        """通过点分路径（如 'model.api_key'）获取嵌套字典的值"""
        if not self._config_data:
            return None
        
        keys = key_path.split('.')
        value = self._config_data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return None
        return value
    
    def get(self, key_path: str, default: Any = None, required: bool = False) -> Any:
        """
        获取配置值。
        
        Args:
            key_path: 配置项的点分路径，例如 'model.api_key'
            default: 默认值（当配置项不存在时返回）
            required: 是否为必需项，如果是必需项但不存在会抛出异常
            
        Returns:
            配置值或默认值
        """
        if self._config_data is None:
            self.logger.warning("配置未加载，正在尝试自动加载", extra={'tag': 'CONFIG_WARN'})
            self.load()  # 自动加载
        
        value = self._get_nested_value(key_path)
        
        if value is None:
            if required:
                error_msg = f"必需的配置项 '{key_path}' 未在配置文件中设置"
                self.logger.error(error_msg, extra={'tag': 'CONFIG_ERROR'})
                raise KeyError(error_msg)
            # 安全日志：对疑似敏感信息的键进行掩码
            if 'key' in key_path.lower() or 'secret' in key_path.lower() or 'token' in key_path.lower():
                self.logger.debug(f"获取配置 {key_path}: (使用默认值或未设置)", extra={'tag': 'CONFIG_GET'})
            else:
                self.logger.debug(f"获取配置 {key_path}: {default} (使用默认值)", extra={'tag': 'CONFIG_GET'})
            return default
        
        # 安全日志
        if isinstance(value, str) and ('key' in key_path.lower() or 'secret' in key_path.lower() or 'token' in key_path.lower()):
            masked_value = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else "***"
            self.logger.debug(f"获取配置 {key_path}: {masked_value}", extra={'tag': 'CONFIG_GET'})
        else:
            self.logger.debug(f"获取配置 {key_path}: {value}", extra={'tag': 'CONFIG_GET'})
        
        return value

# 全局配置实例
config = YAMLConfig()