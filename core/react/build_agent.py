# core/react/build_agent.py
from langgraph.graph import StateGraph, START, END
from core.common.state_define import AgentState
from core.common.model_node import create_model_node
from core.react.agent_logic import should_continue
from core.common.tool_node import create_tool_node


def build_react_graph(model_with_tools, system_prompt: str,
                      session_id: int = None,
                      project_directory: str = None):
    """
    构建 ReAct Agent 的 LangGraph 图。

    Args:
        model_with_tools: 绑定了工具的 ChatOpenAI 实例
        system_prompt: 系统提示词
        session_id: 会话ID（用于状态持久化）
        project_directory: 项目目录（用于状态持久化）

    Returns:
        编译后的 CompiledGraph 实例
    """
    # 创建节点
    react_model_node = create_model_node(model_with_tools, system_prompt)
    tool_executor = create_tool_node(
        session_id=session_id,
        project_directory=project_directory
    )

    # 短任务最终答案节点
    def final_answer_node(state: AgentState):
        """处理最终答案提交的节点"""
        tool_result = tool_executor(state)
        # 标记任务完成
        return {**tool_result, "status": "completed"}

    # 长任务子任务提交节点
    def sub_task_answer_node(state: AgentState):
        """处理长任务子任务提交的节点"""
        return tool_executor(state)

    # 构建图
    graph_builder = StateGraph(AgentState)

    # 添加节点
    graph_builder.add_node("agent", react_model_node)
    graph_builder.add_node("tools", tool_executor)
    graph_builder.add_node("final_answer", final_answer_node)
    graph_builder.add_node("sub_task_answer", sub_task_answer_node)

    # 添加边
    graph_builder.add_edge(START, "agent")

    # 更新条件边
    graph_builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",                  # 调用普通工具 -> 去执行工具
            "end_final": "final_answer",       # 正常提交最终答案 -> 去执行最终答案工具
            "end_sub_task": "sub_task_answer", # 长任务子任务提交 -> 去执行子任务提交工具
            "end_abort": END,                  # 异常退出 -> 直接结束
        }
    )

    graph_builder.add_edge("tools", "agent")
    graph_builder.add_edge("final_answer", END)
    graph_builder.add_edge("sub_task_answer", END)

    return graph_builder.compile()
