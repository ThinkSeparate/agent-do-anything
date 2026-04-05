# core/react/build_agent.py
from langgraph.graph import StateGraph, START, END
from core.common.state_define import AgentState
from core.react.model_node import create_react_model_node
from core.react.agent_logic import should_continue
from core.common.tool_node import create_tool_node


def build_react_graph(model_with_tools, system_prompt: str):
    """
    构建 ReAct Agent 的 LangGraph 图。

    Args:
        model_with_tools: 绑定了工具的 ChatOpenAI 实例
        system_prompt: 系统提示词

    Returns:
        编译后的 CompiledGraph 实例
    """
    # 创建节点
    react_model_node = create_react_model_node(model_with_tools, system_prompt)
    tool_executor = create_tool_node()

    # 构建图
    graph_builder = StateGraph(AgentState)

    # 添加节点
    graph_builder.add_node("agent", react_model_node)
    graph_builder.add_node("tools", tool_executor)

    # 添加边
    graph_builder.add_edge(START, "agent")
    graph_builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END
        }
    )
    graph_builder.add_edge("tools", "agent")

    # 编译
    return graph_builder.compile()
