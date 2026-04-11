# core/react/model_node.py
import logging
from langchain.messages import SystemMessage, HumanMessage, AIMessage, RemoveMessage
from core.common.state_define import AgentState
from utils.message_processor import process_messages_before_send
import json

# 导入具体的异常类型
from openai import BadRequestError as OpenAIBadRequestError


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

        # 准备消息（基础消息，不包含SystemMessage，由process_messages_before_send添加）
        messages_to_send = [SystemMessage(content=system_prompt)] + state["messages"]

        # 调用模型（带重试逻辑，每次重试前统一处理消息）
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            # 【统一处理】验证、截断、生成提示（每次重试前执行）
            processed_messages, process_info = process_messages_before_send(
                messages_to_send,
                logger=logger,
                validate=True,
                truncate=True,
                generate_prompts=(retry_count == 0)  # 只在第一次生成提示，避免重复
            )

            # 记录处理信息（仅在发生变化时）
            if process_info["truncated"] or process_info["prompts_added"] > 0:
                logger.warning(
                    f"消息处理: 截断={process_info['truncated']}(移除{process_info['removed_count']}条), "
                    f"提示={process_info['prompts_added']}条, "
                    f"token {process_info['original_token']} -> {process_info['final_token']}",
                    extra={'tag': 'MSG_PROCESSED'}
                )

            # 记录发送的完整消息到通信日志 (CONV_SEND)
            logger.debug(processed_messages, extra={'tag': 'CONV_SEND'})

            try:
                response = model_with_tools.invoke(processed_messages)
                break  # 成功，跳出循环

            except OpenAIBadRequestError as e:
                # 已知可修复错误：Token溢出或工具调用不匹配
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"达到最大重试次数({max_retries})，放弃重试: {e}", extra={'tag': 'MAX_RETRIES'})
                    raise

                error_msg_lower = str(e).lower()

                # 判断具体子类型，仅用于日志记录
                if 'maximum context length' in error_msg_lower or 'too many tokens' in error_msg_lower:
                    logger.warning(
                        f"Token溢出(尝试{retry_count}/{max_retries})，将由消息处理器自动截断",
                        extra={'tag': 'TOKEN_OVERFLOW'}
                    )
                elif 'tool_calls' in error_msg_lower and 'tool messages' in error_msg_lower:
                    logger.warning(
                        f"工具调用链断裂(尝试{retry_count}/{max_retries})，将由消息处理器自动修复",
                        extra={'tag': 'TOOL_CALL_MISMATCH'}
                    )
                else:
                    logger.warning(
                        f"BadRequestError(尝试{retry_count}/{max_retries})，将由消息处理器处理",
                        extra={'tag': 'BAD_REQUEST'}
                    )
                # 更新 messages_to_send 为处理后的结果，下次重试基于截断/修复后的消息
                messages_to_send = processed_messages
                continue

            except Exception as e:
                # 未知错误，直接抛出不重试
                raise

        # 5. 记录模型回复到通信日志 (CONV_RECV)
        logger.debug(response, extra={'tag': 'CONV_RECV'})

        # 6. 记录 Token 消耗
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

        # 7. 【修改】将完整的tool_calls结构转换为JSON字符串并设置为content
        if hasattr(response, 'tool_calls') and response.tool_calls:
            try:
                tool_calls_data = []
                for tool_call in response.tool_calls:
                    tool_call_dict = {
                        'name': tool_call.get('name', '未知工具'),
                        'id': tool_call.get('id', '未知ID'),
                        'args': tool_call.get('args', {}),
                        'type': tool_call.get('type', 'tool_call')
                    }
                    tool_calls_data.append(tool_call_dict)

                tool_calls_json = json.dumps(tool_calls_data, ensure_ascii=False, indent=2)
                tool_calls_str = f"工具调用信息（原始结构）:\n{tool_calls_json}"

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

        # 8. 处理模型"空响应"情况（无content且无tool_calls）
        if not response.content or not response.content.strip():
            if not getattr(response, 'tool_calls', None):
                logger.warning("模型返回空响应且无工具调用，提示模型继续", extra={'tag': 'MODEL_EMPTY'})
                prompt_msg = HumanMessage(
                    content="你的上一步没有输出内容或调用工具。请继续思考并采取行动，或调用 submit_final_answer 结束任务。"
                )
                return {"messages": [prompt_msg]}

        # 9. 记录其他调试/信息日志
        logger.info(f"发送消息数量: {len(processed_messages)}", extra={'tag': 'MESSAGES'})
        reasoning_content = getattr(response, 'reasoning_content', None)
        if reasoning_content:
            logger.info(f"思考过程: {reasoning_content}", extra={'tag': 'THOUGHT'})
        logger.info("收到模型响应", extra={'tag': 'MODEL_RESPONSE'})

        # 记录模型原始响应
        logger.debug(f"模型原始响应: {response}", extra={'tag': 'MODEL_RAW'})

        # 10. 【关键】持久化截断后的消息：返回 RemoveMessage 删除被截断的消息
        # 比较原始消息和处理后的消息，找出被移除的消息 ID
        original_ids = {getattr(m, 'id', None) for m in state["messages"] if getattr(m, 'id', None)}
        # processed_messages 包含 SystemMessage + 截断后的消息，需要排除 SystemMessage
        processed_state_ids = {getattr(m, 'id', None) for m in processed_messages[1:] if getattr(m, 'id', None)}
        removed_ids = original_ids - processed_state_ids

        return_messages = [response]
        if removed_ids:
            for rid in removed_ids:
                return_messages.insert(0, RemoveMessage(id=rid))
                logger.debug(f"标记删除被截断的消息: {rid}", extra={'tag': 'MSG_REMOVED'})
            logger.info(f"截断持久化: 从state中移除 {len(removed_ids)} 条消息", extra={'tag': 'TRUNCATE_PERSIST'})

        return {"messages": return_messages}

    return react_model_node
