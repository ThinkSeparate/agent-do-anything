# core/react/build_agent.py
from langgraph.graph import StateGraph, START, END
from core.common.state_define import AgentState
from core.common.model_node import create_model_node
from core.react.agent_logic import should_continue
from core.common.tool_node import create_tool_node
from tools import invoke_context_compressor


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
    react_model_node = create_model_node(model_with_tools, system_prompt)
    tool_executor = create_tool_node()
    
    # 创建一个专门处理最终答案的节点
    def final_answer_node(state: AgentState):
        """处理最终答案提交的节点"""
        last_message = state["messages"][-1]
        tool_call = last_message.tool_calls[0]
        
        # 执行 submit_final_answer 工具
        tool_result = tool_executor(state)  # 或者直接调用工具
        
        # 返回结果，标记任务完成
        return {**tool_result, "status": "completed"}
    
    # 构建图
    graph_builder = StateGraph(AgentState)

    # 添加节点
    graph_builder.add_node("agent", react_model_node)
    graph_builder.add_node("tools", tool_executor)
    graph_builder.add_node("final_answer", final_answer_node)
    graph_builder.add_node("compressor", invoke_context_compressor)
    
    # 添加边
    graph_builder.add_edge(START, "agent")
    
    # 更新条件边
    graph_builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",              # 调用普通工具 -> 去执行工具
            "end_normal": "final_answer",  # 正常提交答案 -> 去执行最终答案工具
            "end_abort": END,              # 异常退出 -> 直接结束
        }
    )
    
    # 普通工具执行后, 执行一次压缩，再回到agent节点
    graph_builder.add_edge("tools", "compressor")
    graph_builder.add_edge("compressor", "agent")
    
    # 最终答案工具执行后结束
    graph_builder.add_edge("final_answer", END)
    
    return graph_builder.compile()