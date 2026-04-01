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
        
        self.logger.info(f"LLMClient 初始化完成，模型: {model_name}", 
                        extra={'tag': 'LLM_CLIENT_INIT'})
        
    def _call_once(self, messages: List[Dict[str, str]]) -> str:
        """
        执行单次模型API调用，并返回解析后的文本内容。
        此方法封装了请求发送、响应解析和空内容检查的核心逻辑。

        Args:
            messages: 对话消息列表

        Returns:
            解析到的文本内容。如果`reasoning_content`和`content`字段均为空，则返回空字符串。
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
        )
        self.logger.debug(f"模型返回结果{response}", extra={'tag': 'MODEL_RESPONE'})

        # 解析响应，优先使用 reasoning_content 字段
        message = response.choices[0].message
        reasoning_content = getattr(message, 'reasoning_content', None)
        content = message.content if message.content else reasoning_content

        # 记录使用量统计
        if hasattr(response, 'usage'):
            usage = response.usage
            self.logger.info(f"Token 使用情况 - 提示: {usage.prompt_tokens}, "
                           f"完成: {usage.completion_tokens}, "
                           f"总计: {usage.total_tokens}",
                           extra={'tag': 'API_USAGE'})
        return content

    def call(self, messages: List[Dict[str, str]]) -> str:
        """
        调用大模型API，并在首次响应为空时自动重试一次。
        
        Args:
            messages: 对话消息列表
            
        Returns:
            模型返回的文本内容
            
        Raises:
            RuntimeError: API调用失败或连续返回空响应时
        """
        self.logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})
        
        try:
            # 第一次调用
            content = self._call_once(messages)
            
            # 检查模型响应是否为空或无效
            if not content or content.strip() == "":
                self.logger.warning("模型返回了空响应，准备重试...", extra={'tag': 'MODEL_RETRY'})
                # 直接重试一次
                content = self._call_once(messages)
                if not content or content.strip() == "":
                    raise RuntimeError("模型连续返回空响应，请检查API状态或提示词。")

            # 记录成功日志
            self.logger.info(f"API 调用成功，模型: {self.model_name}", extra={'tag': 'API_SUCCESS'})
            self.logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})
            self.logger.debug(f"模型原始响应:\n{content}", extra={'tag': 'MODEL_RAW'})
            
            return content
            
        except Exception as e:
            self.logger.error(f"API 调用失败: {str(e)}", extra={'tag': 'API_ERROR'})
            # 重新抛出异常，由上层处理
            raise