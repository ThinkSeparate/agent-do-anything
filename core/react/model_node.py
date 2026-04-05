# core/react/model_node.py
import logging
from langchain.messages import SystemMessage, HumanMessage, AIMessage
from core.common.state_define import AgentState

def create_react_model_node(model_with_tools, system_prompt: str):
    """
    创建 ReAct 模型调用节点。
    重构后，此节点将记录通信日志和Token消耗。

    Args:
        model_with_tools: 绑定了工具的 ChatOpenAI 实例
        system_prompt: 系统提示词
    """
    logger = logging.getLogger(__name__)

    def react_model_node(state: AgentState) -> dict:
        """调用 LLM 获取响应，并记录详细日志。"""
        logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})

        # 1. 准备消息
        messages_to_send = [SystemMessage(content=system_prompt)] + state["messages"]
        
        # 2. 【新增】记录发送的完整消息到通信日志 (CONV_SEND)
        conv_send_content = _format_messages_for_log(messages_to_send)
        logger.debug(conv_send_content, extra={'tag': 'CONV_SEND'})
        
        # 3. 调用模型
        response = model_with_tools.invoke(messages_to_send)
        
        # 4. 【修复】记录模型回复到通信日志 (CONV_RECV)
        # 增强健壮性：尝试从多个可能的属性获取回复内容
        response_content = _get_response_content(response)
        logger.debug(response_content, extra={'tag': 'CONV_RECV'})
        
        # 5. 【修改】解析并记录 Token 消耗 (提示词改为中文)
        if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
            usage = response.response_metadata['token_usage']
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            # 关键修改：英文标签改为中文
            logger.info(f"提示令牌={prompt_tokens} 补全令牌={completion_tokens} 总计令牌={total_tokens}",
                        extra={'tag': 'TOKEN_USAGE'})
        elif hasattr(response, 'usage'):
            # 兼容其他可能的usage属性结构
            usage = response.usage
            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            # 关键修改：英文标签改为中文
            logger.info(f"提示令牌={prompt_tokens} 补全令牌={completion_tokens} 总计令牌={total_tokens}",
                        extra={'tag': 'TOKEN_USAGE'})
        else:
            logger.warning("无法从响应中解析Token使用情况。", extra={'tag': 'TOKEN_USAGE'})

        # 6. 记录其他调试/信息日志 (原有逻辑，保持兼容)
        logger.info(f"发送消息数量: {len(messages_to_send)}", extra={'tag': 'MESSAGES'})
        reasoning_content = getattr(response, 'reasoning_content', None)
        if reasoning_content:
            logger.info(f"思考过程: {reasoning_content[:200]}...", extra={'tag': 'THOUGHT'})
        logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})
        logger.debug(f"模型原始响应: {response_content}", extra={'tag': 'MODEL_RAW'})

        return {"messages": [response]}

    return react_model_node


def _format_messages_for_log(messages):
    """
    将消息列表格式化为通信日志中易读的字符串。
    格式：
        [序号] 角色类型
        内容...
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

def _get_response_content(response):
    """
    安全地从模型响应对象中提取内容文本。
    尝试从多个常见属性中获取，避免因属性名为空导致通信日志记录为空。
    
    Args:
        response: 模型调用返回的响应对象。
    
    Returns:
        str: 提取到的内容，如果都为空则返回提示字符串。
    """
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
        return response.get('text') or response.get('content') or str(response)
    
    # 最终回退：转换为字符串
    # 如果响应对象本身是字符串或None，或者没有可用内容，则记录一个占位符
    content = str(response) if response is not None else ''
    return content if content else '[模型回复内容为空或无法解析]'