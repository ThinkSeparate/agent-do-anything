# core/common/model_define.py
import logging
from langchain_openai import ChatOpenAI


def create_chat_model(model_name: str, base_url: str, api_key: str, timeout: int) -> ChatOpenAI:
    """创建 ChatOpenAI 实例。"""
    logger = logging.getLogger(__name__)
    logger.info(f"初始化 ChatOpenAI，模型: {model_name}", extra={'tag': 'MODEL_INIT'})
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )


def bind_tools_to_model(model: ChatOpenAI, tools: list) -> ChatOpenAI:
    """将 LangChain tools 绑定到模型。"""
    logger = logging.getLogger(__name__)
    logger.info(f"绑定 {len(tools)} 个工具到模型", extra={'tag': 'MODEL_BIND_TOOLS'})
    return model.bind_tools(tools)
