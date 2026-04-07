# core/plan/build_agent.py
from langgraph.graph import StateGraph, START, END
from langchain.messages import HumanMessage, AIMessage, ToolMessage
from core.plan.state_define import PlanState
from core.common.tool_node import create_tool_node
from core.plan.agent_logic import should_continue, should_replan
from core.common.model_node import create_model_node
from core.react.agent import ReActAgent
import json
import logging

logger = logging.getLogger(__name__)


def build_plan_graph(model_with_tools, system_prompt: str, project_directory: str):
    """
    构建 Plan Agent 的 LangGraph 图
    
    图结构：
    START → plan_model → 路由 → [各种节点] → END
    """
    # 创建节点
    plan_model_node = create_model_node(model_with_tools, system_prompt)
    tool_node = create_tool_node()
    
    # 创建图构建器
    workflow = StateGraph(PlanState)
    
    # 添加核心节点
    workflow.add_node("plan_agent", plan_model_node)
    workflow.add_node("execute_tool", tool_node)
    
    # === 新增：任务执行节点 ===
    def execute_react_task_node(state: PlanState) -> PlanState:
        """执行分配给 ReAct Agent 的任务"""
        messages = state["messages"]
        last_ai_msg = None
        
        # 找到最后一条 AI 消息
        for msg in reversed(messages):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                last_ai_msg = msg
                break
        
        if not last_ai_msg or not last_ai_msg.tool_calls:
            logger.error("未找到有效的工具调用")
            return state
        
        tool_call = last_ai_msg.tool_calls[0]
        if tool_call.get("name") != "assign_task_to_react":
            logger.error(f"预期 assign_task_to_react，实际是 {tool_call.get('name')}")
            return state
        
        task_description = tool_call.get("args", {}).get("task_description", "")
        task_id = tool_call.get("args", {}).get("task_id", "")
        
        if not task_description:
            logger.error("任务描述为空", extra={'tag': 'EXECUTE_TASK'})
            return state
        
        # ===== 新增：检查任务是否已执行 =====
        completed_tasks = state.get("completed_tasks", [])
        for task in completed_tasks:
            if task.get("task_id") == task_id or task.get("description") == task_description:
                logger.warning(f"任务 '{task_id}' 已执行过，跳过重复执行")
                
                # 返回已存在的结果
                tool_message = ToolMessage(
                    content=f"任务已执行过，使用之前的执行结果。\n结果摘要: {task.get('result', '')}",
                    tool_call_id=tool_call.get("id", "")
                )
                
                new_state = {
                    **state,
                    "messages": state["messages"] + [tool_message]
                }
                return new_state
        
        # 原有的执行逻辑...
        logger.info(f"Plan Agent → ReAct Agent 任务分配", extra={'tag': 'AGENT_COMM'})
        logger.info(f"传递任务描述: {task_description}", extra={'tag': 'AGENT_COMM'})
        logger.info(f"任务ID: {task_id}", extra={'tag': 'AGENT_COMM'})
        logger.info(f"隔离状态: ✅ 只传递任务描述，不传递历史上下文", extra={'tag': 'AGENT_COMM'})
        logger.info(f"创建独立 ReActAgent 实例，无状态共享", extra={'tag': 'AGENT_COMM'})
        
        try:
            # 创建新的 ReActAgent 实例（避免状态污染）
            react_agent = ReActAgent(project_directory=project_directory)
            
            # 执行任务（只传递任务描述，不传递上下文）
            result = react_agent.run(task_description)
            
            # 记录结果
            completed_tasks = state.get("completed_tasks", [])
            completed_tasks.append({
                "task_id": task_id,
                "description": task_description,
                "result": result,
                "status": "success"
            })
            
            # 更新状态
            new_state = {
                **state,
                "completed_tasks": completed_tasks,
                "consecutive_failures": 0,  # 重置失败计数
                "execution_context": {
                    **state.get("execution_context", {}),
                    f"task_{task_id}": result  # 只保留部分结果作为上下文
                }
            }
            
            # 添加结果消息
            tool_message = ToolMessage(
                content=f"任务执行成功。结果摘要: {result}",
                tool_call_id=tool_call.get("id", "")
            )
            
            new_state["messages"] = state["messages"] + [tool_message]
            logger.info(f"ReAct Agent 执行完成，结果长度: {len(result)}", extra={'tag': 'EXECUTE_TASK'})
            
            return new_state
            
        except Exception as e:
            logger.error(f"任务执行失败: {e}")
            
            # 记录失败
            completed_tasks = state.get("completed_tasks", [])
            completed_tasks.append({
                "task_id": task_id,
                "description": task_description,
                "result": str(e),
                "status": "failed"
            })
            
            # 更新状态
            new_state = {
                **state,
                "completed_tasks": completed_tasks,
                "consecutive_failures": state.get("consecutive_failures", 0) + 1
            }
            
            # 添加错误消息
            tool_message = ToolMessage(
                content=f"任务执行失败: {str(e)}",
                tool_call_id=tool_call.get("id", "")
            )
            
            new_state["messages"] = state["messages"] + [tool_message]
            return new_state
    
    workflow.add_node("execute_react_task", execute_react_task_node)
    
    # === 新增：重新规划节点 ===
    def replan_node(state: PlanState) -> PlanState:
        """
        处理重新规划逻辑
        """
        logger.info("触发重新规划")
        
        # 获取失败信息
        messages = state["messages"]
        last_tool_msg = None
        
        for msg in reversed(messages):
            if msg.type == "tool" and "失败" in msg.content:
                last_tool_msg = msg
                break
        
        failure_reason = "未知原因"
        if last_tool_msg:
            failure_reason = last_tool_msg.content
        
        # 更新状态为重新规划模式
        new_state = {
            **state,
            "current_phase": "replanning",
            "pending_tasks": [],  # 清空待处理任务
            "execution_context": {
                **state.get("execution_context", {}),
                "last_failure": failure_reason,
                "completed_count": len(state.get("completed_tasks", []))
            }
        }
        
        # 添加系统提示
        replan_prompt = HumanMessage(
            content=f"需要重新规划。失败原因: {failure_reason}\n"
                   f"已完成任务: {len(state.get('completed_tasks', []))} 个\n"
                   f"请基于当前上下文调整计划。"
        )
        
        new_state["messages"] = state["messages"] + [replan_prompt]
        return new_state
    
    workflow.add_node("replan_node", replan_node)
    
    # === 新增：最终报告节点 ===
    def final_report_node(state: PlanState) -> PlanState:
        """
        生成并提交最终报告
        """
        logger.info("生成最终报告")
        
        # 生成报告
        completed = state.get("completed_tasks", [])
        original_task = state.get("original_task", "")
        
        success_tasks = [t for t in completed if t.get("status") == "success"]
        failed_tasks = [t for t in completed if t.get("status") == "failed"]
        
        report = f"""# 任务执行报告
原始任务: {original_task}

## 执行摘要
- 总任务数: {len(completed)}
- 成功: {len(success_tasks)}
- 失败: {len(failed_tasks)}
- 重新规划次数: {state.get('replan_count', 0)}

## 详细结果
"""
        
        for i, task in enumerate(completed, 1):
            status_icon = "✅" if task.get("status") == "success" else "❌"
            report += f"{i}. {status_icon} {task.get('task_id', f'task_{i}')}: {task.get('description', '')}\n"
        
        # 添加总结
        if failed_tasks:
            report += f"\n## 注意\n有 {len(failed_tasks)} 个任务失败，可能需要人工干预。"
        else:
            report += f"\n## 状态\n所有任务已成功完成。"
        
        # 调用工具提交报告
        tool_call = {
            "name": "submit_plan_report",
            "args": {"final_report": report},
            "id": "final_report_call"
        }
        
        ai_message = AIMessage(
            content="生成最终执行报告",
            tool_calls=[tool_call]
        )
        
        # 执行工具
        tool_state = {"messages": [ai_message]}
        tool_result = tool_node(tool_state)
        
        new_state = {
            **state,
            "messages": state["messages"] + [ai_message] + tool_result["messages"],
            "current_phase": "completed"
        }
        
        return new_state
    
    workflow.add_node("final_report", final_report_node)
    
    # === 配置图结构 ===
    
    # 初始边
    workflow.add_edge(START, "plan_agent")
    
    # 条件边（从 plan_agent 出发）
    workflow.add_conditional_edges(
        "plan_agent",
        should_continue,
        {
            "execute_plan": "execute_react_task",  # 分配任务 → 执行
            "replan": "replan_node",              # 重新规划 → 重规划节点
            "ask_user": "execute_tool",           # 询问用户 → 工具节点
            "finalize": "final_report"            # 完成 → 最终报告
        }
    )
    
    # 工具执行后回到 plan_agent
    workflow.add_edge("execute_tool", "plan_agent")
    
    # 任务执行后回到 plan_agent（继续规划或分配下一个任务）
    workflow.add_edge("execute_react_task", "plan_agent")
    
    # 重新规划后回到 plan_agent
    workflow.add_edge("replan_node", "plan_agent")
    
    # 最终报告后结束
    workflow.add_edge("final_report", END)
    
    return workflow.compile()