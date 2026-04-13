# core/react/model_node.py
import logging
from langchain.messages import SystemMessage, HumanMessage, AIMessage, RemoveMessage
from core.common.state_define import AgentState
from utils.message_processor import process_messages_before_send
import json

# 导入具体的异常类型
from openai import BadRequestError as OpenAIBadRequestError


def _assign_index(msg, next_index: int) -> int:
    """
    为消息分配固定索引。
    如果消息已有索引则保持不变，否则分配新索引并存储在 msg.index 中。
    返回下一个可用的索引。
    """
    if hasattr(msg, 'index') and msg.index is not None:
        return max(next_index, msg.index + 1)
    # 分配新索引
    msg.index = next_index
    return next_index + 1


def _get_max_index(messages) -> int:
    """从消息列表中获取最大索引"""
    max_idx = 0
    for msg in messages:
        if hasattr(msg, 'index') and msg.index is not None:
            max_idx = max(max_idx, msg.index)
    return max_idx


def _format_message_for_model(msg) -> str:
    """
    将消息格式化为带索引的字符串格式，用于发送给模型。
    格式: index: X\ncontent: Z
    """
    from langchain.messages import ToolMessage, AIMessage

    index = getattr(msg, 'index', '?')

    # 构建键值对格式的内容
    lines = [f"index: {index}"]

    # ToolMessage 添加 tool_call_id
    if isinstance(msg, ToolMessage):
        lines.append(f"tool_call_id: {msg.tool_call_id}")

    # 添加原始 content
    lines.append(f"content: {msg.content or ''}")

    # AIMessage 有 tool_calls 时添加
    if isinstance(msg, AIMessage):
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            lines.append(f"tool_calls: {tool_calls}")

    return "\n".join(lines)


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
        # 1. 为没有索引的消息分配索引（直接修改原始消息）
        next_index = _get_max_index(state["messages"]) + 1
        for msg in state["messages"]:
            next_index = _assign_index(msg, next_index)

        # 2. 创建带索引标记的消息副本用于发送给模型
        formatted_messages = []
        for msg in state["messages"]:
            formatted_content = _format_message_for_model(msg)
            # 创建副本，只修改 content
            if isinstance(msg, HumanMessage):
                formatted_msg = HumanMessage(
                    content=formatted_content,
                    id=msg.id,
                    additional_kwargs=dict(getattr(msg, "additional_kwargs", {}))
                )
                formatted_msg.index = msg.index  # 复制 index
            elif isinstance(msg, AIMessage):
                formatted_msg = AIMessage(
                    content=formatted_content,
                    id=msg.id,
                    tool_calls=getattr(msg, "tool_calls", None),
                    additional_kwargs=dict(getattr(msg, "additional_kwargs", {}))
                )
                formatted_msg.index = msg.index
            elif isinstance(msg, RemoveMessage):
                formatted_msg = RemoveMessage(id=msg.id)
            else:
                # ToolMessage 或其他类型
                from langchain.messages import ToolMessage
                if isinstance(msg, ToolMessage):
                    formatted_msg = ToolMessage(
                        content=formatted_content,
                        tool_call_id=msg.tool_call_id,
                        id=msg.id,
                        additional_kwargs=dict(getattr(msg, "additional_kwargs", {}))
                    )
                    formatted_msg.index = msg.index
                else:
                    formatted_msg = msg
            formatted_messages.append(formatted_msg)

        messages_to_send = [SystemMessage(content=system_prompt)] + formatted_messages

        # 调用模型（带重试逻辑，每次重试前统一处理消息）
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            # 【统一处理】清理、截断、生成提示（每次重试前执行）
            # 注意：消息验证修复逻辑已转移到 message_validator 模块
            processed_messages, process_info = process_messages_before_send(
                messages_to_send,
                logger=logger,
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
                logger.info("正在向模型发送请求...", extra={'tag': 'MODEL_REQUEST'})
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
                        f"工具调用链断裂(尝试{retry_count}/{max_retries})，需要验证修复",
                        extra={'tag': 'TOOL_CALL_MISMATCH'}
                    )
                    # 【新增】调用完整验证修复（包含用户交互）
                    from core.common.message_validator import validate_and_repair, MessageValidationError
                    success, repaired_messages = validate_and_repair(
                        messages_to_send, logger=logger
                    )
                    if success:
                        messages_to_send = repaired_messages
                        logger.info("验证修复成功，继续任务", extra={'tag': 'VALIDATION_REPAIRED'})
                        continue  # 修复后重试
                    # 用户拒绝修复时 validate_and_repair 会抛出 MessageValidationError
                    # 直接跳出重试循环，由外层 agent 统一处理
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
                # 计算新消息的索引（基于当前最大索引+1）
                max_idx = _get_max_index(state["messages"])
                # 使用 HumanMessage 伪装成用户提示，模型理解最自然
                prompt_msg = HumanMessage(
                    content="【系统提示】你的上一步没有输出内容或调用工具。请继续思考并采取行动，或调用 submit_final_answer 结束任务。"
                )
                prompt_msg.index = max_idx + 1  # 分配索引
                return {"messages": [prompt_msg]}

        # 9. 给模型响应消息分配索引
        max_idx = _get_max_index(state["messages"])
        if not hasattr(response, 'index') or response.index is None:
            response.index = max_idx + 1

        # 10. 记录其他调试/信息日志
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
            # 【修复】只删除当前 state 中确实存在的消息，避免重复删除导致错误
            current_state_msg_ids = {getattr(m, 'id', None) for m in state["messages"] if getattr(m, 'id', None)}
            valid_removed_ids = removed_ids & current_state_msg_ids
            for rid in valid_removed_ids:
                return_messages.insert(0, RemoveMessage(id=rid))
                logger.debug(f"标记删除被截断的消息: {rid}", extra={'tag': 'MSG_REMOVED'})
            if valid_removed_ids:
                logger.info(f"截断持久化: 从state中移除 {len(valid_removed_ids)} 条消息", extra={'tag': 'TRUNCATE_PERSIST'})

        return {"messages": return_messages}

    return react_model_node
