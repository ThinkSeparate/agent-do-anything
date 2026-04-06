# core/clarify/build_agent.py (优化版本)
from langgraph.graph import StateGraph, START, END
from langchain.messages import HumanMessage
from core.common.state_define import AgentState
from core.common.tool_node import create_tool_node
from core.clarify.agent_logic import should_continue
from core.common.model_node import create_model_node


def build_clarify_graph(model_with_tools, system_prompt: str):
    """
    构建需求澄清Agent的LangGraph图。
    图结构：START -> (clarify_model) -> (路由) -> [ ask_user工具 -> clarify_model | final_answer节点 | transfer_react节点 ] -> END
    """
    # 创建节点
    clarify_model_node = create_model_node(model_with_tools, system_prompt)
    tool_node = create_tool_node()  # 用于执行ask_user等工具

    # 创建图构建器
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("clarify_agent", clarify_model_node)
    workflow.add_node("execute_tool", tool_node)

    # --- 新增：专门处理最终答案的节点 ---
    def final_answer_node(state: AgentState):
        """
        处理并执行 submit_final_answer 工具调用的节点。
        执行后，将结果放入状态，流程结束。
        """
        # 调用工具执行节点来处理 submit_final_answer
        result_state = tool_node(state)
        # 可以选择在此处添加任务完成的状态标记，例如：
        # result_state["status"] = "completed_by_clarify"
        return result_state
    # --- 新增结束 ---
    workflow.add_node("final_answer", final_answer_node)

    # 设置初始边
    workflow.add_edge(START, "clarify_agent")

    # 设置条件边（由clarify_agent节点出发，根据调用的工具决定下一步）
    workflow.add_conditional_edges(
        "clarify_agent",
        should_continue,  # 路由函数
        {
            "ask_user": "execute_tool",        # 需要继续提问 -> 执行ask_user工具
            "end_direct": "final_answer",      # **修改点**：直接回答 -> 去执行final_answer工具节点
            "transfer_react": "transfer_react_node",  # 复杂需求 -> 转到专门的处理节点
        }
    )

    # 工具执行后，继续回到clarify_agent进行下一轮思考
    workflow.add_edge("execute_tool", "clarify_agent")
    # **修改点**：final_answer节点执行后，流程结束
    workflow.add_edge("final_answer", END)

    # 处理复杂需求转移的节点（这是一个虚拟节点，实际触发ReActAgent的调用）
    def transfer_to_react_node(state: AgentState):
        """
        提取已澄清的任务描述，准备转交给ReActAgent。
        """
        clarified_task = ""
        
        # 从AI消息中提取transfer_to_react调用的参数
        ai_messages = [msg for msg in state["messages"] if msg.type == "ai"]
        for msg in reversed(ai_messages):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get("name") == "transfer_to_react":
                        tool_args = tool_call.get("args", {})
                        clarified_task = tool_args.get("clarified_task_description", "")
                        break
                if clarified_task:
                    break
        
        # 如果没有找到，从最后一条用户消息提取
        if not clarified_task:
            for msg in reversed(state["messages"]):
                if msg.type == "human":
                    clarified_task = msg.content
                    break
        
        # 如果还是没有，使用初始输入
        if not clarified_task and state["messages"]:
            clarified_task = state["messages"][0].content
            
        return {
            **state,
            "clarified_task": clarified_task,
            "need_react": True,  # 转移标志
            "messages": state["messages"] + [HumanMessage(
                content=f"[系统] 需求澄清完成，任务已转交给执行Agent。任务描述: {clarified_task}"
            )]
        }
    
    workflow.add_node("transfer_react_node", transfer_to_react_node)
    workflow.add_edge("transfer_react_node", END)
    
    return workflow.compile()