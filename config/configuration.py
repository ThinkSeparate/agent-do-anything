# config/configuration.py
import os
from typing import Any, Optional
from dotenv import load_dotenv
import logging

class Config:
    """集中式配置管理器，统一处理环境变量加载和验证"""
    
    _instance = None
    _loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            self.logger = logging.getLogger(__name__)
            self._cache = {}
            self._required_keys = []
            self._initialized = True
    
    def load(self, required_keys: Optional[list] = None) -> None:
        """加载环境变量并验证必需项"""
        if self._loaded:
            return
        
        load_dotenv()
        self.logger.info("正在加载环境变量配置", extra={'tag': 'CONFIG_LOAD'})
        
        if required_keys:
            self._required_keys = required_keys
            self._validate_required_keys()
        
        self._loaded = True
        self.logger.info("环境变量配置加载完成", extra={'tag': 'CONFIG_LOAD'})
    
    def _validate_required_keys(self) -> None:
        """验证必需的环境变量是否已设置"""
        missing_keys = []
        for key in self._required_keys:
            if not os.getenv(key):
                missing_keys.append(key)
        
        if missing_keys:
            error_msg = f"缺少必需的环境变量: {', '.join(missing_keys)}"
            self.logger.critical(error_msg, extra={'tag': 'CONFIG_ERROR'})
            raise ValueError(error_msg)
    
    def get(self, key: str, default: Any = None, required: bool = False) -> Any:
        """
        获取环境变量值
        
        Args:
            key: 环境变量名
            default: 默认值（当环境变量不存在时返回）
            required: 是否为必需项，如果是必需项但不存在会抛出异常
            
        Returns:
            环境变量值或默认值
        """
        if not self._loaded:
            self.logger.warning("配置未显式加载，正在自动加载", extra={'tag': 'CONFIG_WARN'})
            self.load()
        
        # 优先从缓存获取
        if key in self._cache:
            return self._cache[key]
        
        value = os.getenv(key, default)
        
        if required and value is None:
            error_msg = f"必需的环境变量 '{key}' 未设置"
            self.logger.error(error_msg, extra={'tag': 'CONFIG_ERROR'})
            raise ValueError(error_msg)
        
        # 安全记录敏感信息
        if 'key' in key.lower() or 'secret' in key.lower() or 'token' in key.lower():
            masked_value = self._mask_sensitive_value(value) if value else "未设置"
            self.logger.debug(f"获取环境变量 {key}: {masked_value}", extra={'tag': 'CONFIG_GET'})
        else:
            self.logger.debug(f"获取环境变量 {key}: {value}", extra={'tag': 'CONFIG_GET'})
        
        self._cache[key] = value
        return value
    
    def _mask_sensitive_value(self, value: str) -> str:
        """掩码敏感信息（如API密钥）"""
        if not value or len(value) <= 8:
            return "***"
        return value[:4] + "*" * (len(value) - 8) + value[-4:]
    
    def get_all(self, keys: list) -> dict:
        """批量获取多个环境变量"""
        return {key: self.get(key) for key in keys}

# 全局配置实例
config = Config()