# core/common/tool_node.py
import logging
from langchain.messages import ToolMessage, HumanMessage
from core.common.state_define import AgentState
from tools import tools_by_name


def create_tool_node(max_consecutive_failures: int = 3):
    """
    创建工具执行节点。

    Args:
        max_consecutive_failures: 最大连续失败次数，超过后注入恢复提示
    """
    logger = logging.getLogger(__name__)

    def tool_node(state: AgentState) -> dict:
        """执行工具调用并返回结果。"""
        tool_calls = state["messages"][-1].tool_calls
        consecutive_failures = state.get("consecutive_failures", 0)

        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            logger.info(f"执行工具: {tool_name}, 参数: {args}", extra={'tag': 'TOOL_CALL'})

            tool = tools_by_name.get(tool_name)
            if tool is None:
                content = f"工具 '{tool_name}' 不存在。可用工具: {list(tools_by_name.keys())}"
                consecutive_failures += 1
                logger.error(content, extra={'tag': 'TOOL_ERROR'})
            else:
                try:
                    content = tool.invoke(args)
                    consecutive_failures = 0
                    logger.info(f"工具 {tool_name} 执行成功", extra={'tag': 'TOOL_SUCCESS'})
                except Exception as e:
                    content = f"工具 {tool_name} 执行出错: {e}"
                    consecutive_failures += 1
                    logger.error(content, extra={'tag': 'TOOL_FAILURE'})

            results.append(ToolMessage(content=str(content), tool_call_id=tool_call["id"]))

        # 连续失败恢复：注入恢复提示
        if consecutive_failures >= max_consecutive_failures:
            recovery_prompt = (
                f"注意：当前步骤已连续失败 {consecutive_failures} 次。\n"
                f"你必须立即停止当前方法，彻底分析失败原因，并尝试一个完全不同的新策略。\n"
                f"如果无法继续，请直接回复最终答案报告遇到的阻塞。"
            )
            results.append(HumanMessage(content=recovery_prompt))
            logger.warning("已注入恢复提示，引导模型调整策略。", extra={'tag': 'STRATEGY_SHIFT'})
            consecutive_failures = 0

        return {"messages": results, "consecutive_failures": consecutive_failures}

    return tool_node
