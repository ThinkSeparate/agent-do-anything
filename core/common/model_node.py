# core/react/model_node.py
import logging
from langchain.messages import SystemMessage, HumanMessage, AIMessage
from core.common.state_define import AgentState
import json

def create_model_node(model_with_tools, system_prompt: str):
    """
    创建模型调用节点。
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
        
        # 2. 记录发送的完整消息到通信日志 (CONV_SEND)
        # 直接传递原始消息对象，由日志系统负责格式化
        logger.debug(messages_to_send, extra={'tag': 'CONV_SEND'})
        
        # 3. 调用模型
        try:
            response = model_with_tools.invoke(messages_to_send)
        except Exception as e:
            error_msg = str(e).lower()
            # 检查是否是token超限错误
            if any(keyword in error_msg for keyword in ['token', 'context', 'length', 'maximum', 'exceed', 'overflow']):
                logger.critical(
                    f"模型调用时token/context超限: {e}",
                    extra={'tag': 'TOKEN_OVERFLOW'}
                )
                # 返回一个特殊的AIMessage，让系统知道需要压缩
                from langchain.messages import AIMessage
                return {"messages": [AIMessage(
                    content="【系统错误】上下文已超出模型处理上限。请立即调用压缩工具（compress_message或compress_paragraph）大幅压缩历史消息后再继续。建议：1. 使用compress_paragraph压缩早期消息段落 2. 对早期tool结果使用clear操作",
                    additional_kwargs={"token_overflow": True}
                )]}
            else:
                # 其他错误，重新抛出
                raise
        
        # 4. 记录模型回复到通信日志 (CONV_RECV)
        # 直接传递原始响应对象，由日志系统负责格式化
        logger.debug(response, extra={'tag': 'CONV_RECV'})
        
        # 5. 记录 Token 消耗
        if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
            usage = response.response_metadata['token_usage']
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            logger.info(f"提示令牌={prompt_tokens} 补全令牌={completion_tokens} 总计令牌={total_tokens}",
                        extra={'tag': 'TOKEN_USAGE'})
        elif hasattr(response, 'usage'):
            usage = response.usage
            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            logger.info(f"提示令牌={prompt_tokens} 补全令牌={completion_tokens} 总计令牌={total_tokens}",
                        extra={'tag': 'TOKEN_USAGE'})
        else:
            logger.warning("无法从响应中解析Token使用情况。", extra={'tag': 'TOKEN_USAGE'})

        # 6. 【修改】将完整的tool_calls结构转换为JSON字符串并设置为content
        if hasattr(response, 'tool_calls') and response.tool_calls:
            # 将完整的tool_calls结构转换为JSON字符串
            try:
                # 将tool_calls转换为可JSON序列化的格式
                tool_calls_data = []
                for tool_call in response.tool_calls:
                    tool_call_dict = {
                        'name': tool_call.get('name', '未知工具'),
                        'id': tool_call.get('id', '未知ID'),
                        'args': tool_call.get('args', {}),
                        'type': tool_call.get('type', 'tool_call')
                    }
                    tool_calls_data.append(tool_call_dict)
                
                # 转换为格式化的JSON字符串
                tool_calls_json = json.dumps(tool_calls_data, ensure_ascii=False, indent=2)
                tool_calls_str = f"工具调用信息（原始结构）:\n{tool_calls_json}"
                
                # 将tool_calls字符串设置为response的content
                if response.content and response.content.strip():
                    response.content = response.content + "\n\n" + tool_calls_str
                else:
                    response.content = tool_calls_str
                
                logger.debug(f"已设置完整的tool_calls结构到content",
                            extra={'tag': 'TOOL_CALLS_TO_CONTENT'})
                
            except Exception as e:
                logger.error(f"转换tool_calls为JSON时出错: {e}",
                            extra={'tag': 'TOOL_CALLS_ERROR'})
                # 回退到原来的格式化方法
                tool_calls_str = "工具调用信息:\n"
                for i, tool_call in enumerate(response.tool_calls, 1):
                    tool_name = tool_call.get('name', '未知工具')
                    args = tool_call.get('args', {})
                    tool_id = tool_call.get('id', '未知ID')
                    
                    # 格式化参数
                    args_str = "\n  ".join([f"{key}: {value}" for key, value in args.items()])
                    
                    tool_calls_str += f"\n{i}. 工具: {tool_name}\n"
                    tool_calls_str += f"   ID: {tool_id}\n"
                    tool_calls_str += f"   参数:\n  {args_str}\n"
                
                if response.content and response.content.strip():
                    response.content = response.content + "\n\n" + tool_calls_str
                else:
                    response.content = tool_calls_str
            
            logger.debug(f"已将tool_calls内容设置为content: {tool_calls_str}",
                        extra={'tag': 'TOOL_CALLS_TO_CONTENT'})
        
        # 7. 处理模型"空响应"情况（无content且无tool_calls）
        if not response.content or not response.content.strip():
            if not getattr(response, 'tool_calls', None):
                logger.warning("模型返回空响应且无工具调用，提示模型继续", extra={'tag': 'MODEL_EMPTY'})
                # 添加提示让模型继续
                prompt_msg = HumanMessage(
                    content="你的上一步没有输出内容或调用工具。请继续思考并采取行动，或调用 submit_final_answer 结束任务。"
                )
                return {"messages": [prompt_msg]}

        # 8. 记录其他调试/信息日志
        logger.info(f"发送消息数量: {len(messages_to_send)}", extra={'tag': 'MESSAGES'})
        reasoning_content = getattr(response, 'reasoning_content', None)
        if reasoning_content:
            logger.info(f"思考过程: {reasoning_content}", extra={'tag': 'THOUGHT'})
        logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})

        # 记录模型原始响应（使用日志系统中的格式化函数）
        logger.debug(f"模型原始响应: {response}", extra={'tag': 'MODEL_RAW'})

        return {"messages": [response]}

    return react_model_node