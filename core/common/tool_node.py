# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage
from langchain_core.messages import BaseMessage
from langgraph.graph.message import RemoveMessage
from core.common.state_define import AgentState
from tools import tools_by_name
from typing import List


def create_tool_node(max_consecutive_failures: int = 3):
    """
    创建工具执行节点，包含压缩功能。
    """
    logger = logging.getLogger(__name__)
    
    def execute_real_compression(messages: List[BaseMessage], operations: List[dict]) -> List[BaseMessage]:
        """
        实际执行压缩操作的函数
        
        Args:
            messages: 当前消息列表
            operations: 压缩操作策略
            
        Returns:
            消息更新列表（用于add_messages处理）
        """
        updates = []
        
        for i, op in enumerate(operations):
            msg_idx = op.get("message_index")
            op_type = op.get("operation")
            
            if not (0 <= msg_idx < len(messages)):
                logger.warning(f"压缩操作{i}：索引{msg_idx}越界，跳过")
                continue
                
            target_msg = messages[msg_idx]
            
            try:
                if op_type == "delete":
                    # 删除消息
                    updates.append(RemoveMessage(id=target_msg.id))
                    logger.info(f"压缩操作{i}：删除索引{msg_idx}的消息")
                    
                elif op_type == "summarize":
                    summary = op.get("summary_text", "").strip()
                    if summary:
                        # 创建摘要消息（替换原消息）
                        from langchain_core.messages import AIMessage
                        
                        new_msg = AIMessage(
                            content=f"[摘要] {summary}",
                            id=target_msg.id,
                            additional_kwargs={
                                **getattr(target_msg, "additional_kwargs", {}),
                                "original_index": msg_idx,
                                "compressed": True
                            }
                        )
                        updates.append(new_msg)
                        logger.info(f"压缩操作{i}：摘要索引{msg_idx}的消息")
                        
            except Exception as e:
                logger.error(f"压缩操作{i}执行失败: {e}")
                
        return updates

    def tool_node(state: AgentState) -> dict:
        """执行工具调用，包含压缩处理"""
        messages = state["messages"]  # 获取完整消息列表
        tool_calls = state["messages"][-1].tool_calls
        consecutive_failures = state.get("consecutive_failures", 0)
        
        tool_results = []  # ToolMessage结果
        message_updates = []  # 消息更新（压缩、删除等）
        has_compression = False
        compression_success = False
        
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})
            
            # 特殊处理：压缩工具
            if tool_name == "compress_messages":
                has_compression = True
                
                try:
                    # 1. 调用压缩工具获取操作策略
                    tool = tools_by_name.get(tool_name)
                    if tool is None:
                        content = f"工具 '{tool_name}' 不存在"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        consecutive_failures += 1
                        continue
                        
                    # 2. 获取压缩策略
                    result = tool.invoke(args)
                    operations = result.get("operations", []) if isinstance(result, dict) else []
                    
                    if not operations:
                        content = "压缩工具返回空操作列表"
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.warning(content, extra={'tag': 'COMPRESS_EMPTY'})
                        continue
                        
                    # 3. 执行实际压缩
                    compression_updates = execute_real_compression(messages, operations)
                    
                    if compression_updates:
                        message_updates.extend(compression_updates)
                        compression_success = True
                        content = f"成功压缩了 {len(compression_updates)} 条消息"
                        logger.info(content, extra={'tag': 'COMPRESS_SUCCESS'})
                    else:
                        content = "压缩操作未产生任何更新"
                        logger.warning(content, extra={'tag': 'COMPRESS_NO_UPDATE'})
                        
                    # 4. 返回压缩结果
                    tool_results.append(ToolMessage(
                        content=content,
                        tool_call_id=tool_call["id"],
                        additional_kwargs={"compression_success": compression_success}
                    ))
                    
                except Exception as e:
                    content = f"压缩处理出错: {e}"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'COMPRESS_FAILURE'})
                    
            else:
                # 正常工具调用
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    content = f"工具 '{tool_name}' 不存在。可用工具: {list(tools_by_name.keys())}"
                    tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'TOOL_ERROR'})
                else:
                    try:
                        content = tool.invoke(args)
                        consecutive_failures = 0
                        tool_results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))
                        logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})
                    except Exception as e:
                        content = f"工具 {tool_name} 执行出错: {e}"
                        consecutive_failures += 1
                        tool_results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
                        logger.error(content, extra={'tag': 'TOOL_FAILURE'})
        
        # 合并结果：消息更新 + 工具结果
        all_results = message_updates + tool_results
        
        # 如果执行了压缩操作，添加压缩标记
        if has_compression and compression_success:
            all_results.append(HumanMessage(
                content=f"已成功压缩上下文，移除了冗余信息。请基于压缩后的上下文继续。",
                additional_kwargs={"compression_complete": True}
            ))
        
        # 连续失败恢复机制
        if consecutive_failures >= max_consecutive_failures:
            recovery_prompt = (
                f"注意：已连续失败 {consecutive_failures} 次。\n"
                f"请立即停止当前方法，彻底分析失败原因，并尝试完全不同的新策略。\n"
                f"如无法继续，请直接回复最终答案报告阻塞。"
            )
            all_results.append(HumanMessage(content=recovery_prompt))
            logger.warning("已注入恢复提示", extra={'tag': 'STRATEGY_SHIFT'})
            consecutive_failures = 0
        
        return {"messages": all_results, "consecutive_failures": consecutive_failures}
    
    return tool_node