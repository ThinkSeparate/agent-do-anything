# core/llm_client.py
import logging
from typing import List, Dict, Any

from openai import OpenAI
from dotenv import load_dotenv
import os


class LLMClient:
    """大语言模型客户端，封装所有API交互逻辑。"""

    def __init__(self, model_name: str, base_url: str, api_key: str):
        self.logger = logging.getLogger(__name__)
        self.logger.info("LLMClient 初始化开始", extra={'tag': 'LLM_CLIENT_INIT'})
        
        self.model_name = model_name
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        
        self.logger.info(f"LLMClient 初始化完成，模型: {model_name}", extra={'tag': 'LLM_CLIENT_INIT'})

    @staticmethod
    def get_env(env_key: str) -> str:
        """从环境变量加载配置。"""
        load_dotenv()
        value = os.getenv(env_key)
        if not value:
            error_msg = f"未找到 {env_key} 环境变量，请在 .env 文件中设置。"
            logging.error(error_msg, extra={'tag': 'ENV_ERROR'})
            raise ValueError(error_msg)
        
        # 安全地记录环境变量（隐藏敏感信息的部分）
        masked_value = value[:4] + "*" * (len(value) - 8) + value[-4:] if len(value) > 8 else "***"
        logging.debug(f"已加载环境变量 {env_key}: {masked_value}", extra={'tag': 'ENV_LOAD'})
        return value

    def call(self, messages: List[Dict[str, str]]) -> str:
        """
        调用大模型API并返回响应内容。
        
        Args:
            messages: 对话消息列表
            
        Returns:
            模型返回的文本内容
            
        Raises:
            RuntimeError: API调用失败或连续返回空响应时
        """
        self.logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
            )
            
            content = response.choices[0].message.content

            # 检查模型响应是否为空或无效
            if not content or content.strip() == "":
                self.logger.warning("模型返回了空响应，准备重试...", extra={'tag': 'MODEL_RETRY'})
                # 直接重试一次
                retry_response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                )
                content = retry_response.choices[0].message.content
                if not content or content.strip() == "":
                    raise RuntimeError("模型连续返回空响应，请检查API状态或提示词。")

            # 记录 API 调用统计信息
            self.logger.info(f"API 调用成功，模型: {self.model_name}", extra={'tag': 'API_SUCCESS'})
            if hasattr(response, 'usage'):
                usage = response.usage
                self.logger.info(f"Token 使用情况 - 提示: {usage.prompt_tokens}, "
                               f"完成: {usage.completion_tokens}, "
                               f"总计: {usage.total_tokens}",
                               extra={'tag': 'API_USAGE'})
            
            self.logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})
            self.logger.debug(f"模型原始响应:\n{content}", extra={'tag': 'MODEL_RAW'})
            
            return content
            
        except Exception as e:
            self.logger.error(f"API 调用失败: {str(e)}", extra={'tag': 'API_ERROR'})
            # 重新抛出异常，由上层处理
            raise