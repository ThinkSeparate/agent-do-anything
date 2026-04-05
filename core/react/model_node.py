# core/react/model_node.py
import logging
from langchain.messages import SystemMessage
from core.common.state_define import AgentState


def create_react_model_node(model_with_tools, system_prompt: str):
    """
    创建 ReAct 模型调用节点。

    Args:
        model_with_tools: 绑定了工具的 ChatOpenAI 实例
        system_prompt: 系统提示词
    """
    logger = logging.getLogger(__name__)

    def react_model_node(state: AgentState) -> dict:
        """调用 LLM 获取响应。"""
        logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})

        messages_to_send = [SystemMessage(content=system_prompt)] + state["messages"]

        # 记录消息数量
        logger.info(f"发送消息数量: {len(messages_to_send)}", extra={'tag': 'MESSAGES'})

        response = model_with_tools.invoke(messages_to_send)

        # 记录推理过程（如果模型支持）
        reasoning_content = getattr(response, 'reasoning_content', None)
        if reasoning_content:
            logger.info(f"思考过程: {reasoning_content[:200]}...", extra={'tag': 'THOUGHT'})

        logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})
        logger.debug(f"模型原始响应: {response.content}", extra={'tag': 'MODEL_RAW'})

        return {"messages": [response]}

    return react_model_node
