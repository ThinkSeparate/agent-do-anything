# core/plan/agent_logic.py
from typing import Literal
from core.plan.state_define import PlanState
import logging  # 添加标准logging导入


# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)


def should_continue(state: PlanState) -> Literal["execute_plan", "replan", "ask_user", "finalize"]:
    """
    Plan Agent 路由函数
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # 使用标准日志记录
    logger.info(f"检查最后消息类型: {last_message.type}", extra={'tag': 'ROUTING'})
    
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        logger.info("无工具调用，需要重新思考", extra={'tag': 'ROUTING'})
        return "ask_user"
    
    first_tool_call = last_message.tool_calls[0]
    tool_name = first_tool_call.get("name", "")
    logger.info(f"检测到工具调用: {tool_name}", extra={'tag': 'ROUTING'})
    
    # 检查任务完成状态
    completed_tasks = state.get("completed_tasks", [])
    original_task = state.get("original_task", "")
    
    if tool_name == "assign_task_to_react":
        # 检查是否已执行过相同任务
        task_description = first_tool_call.get("args", {}).get("task_description", "")
        for task in completed_tasks:
            if task.get("description") == task_description:
                logger.warning(f"重复任务检测: 任务'{task_description}' 已执行", 
                               extra={'tag': 'ROUTING'})
                return "ask_user"  # 让 Plan Agent 重新思考
        
        logger.info("执行新任务", extra={'tag': 'ROUTING'})
        return "execute_plan"
    elif tool_name == "replan_tool":
        logger.info("需要重新规划", extra={'tag': 'ROUTING'})
        return "replan"
    elif tool_name == "ask_user":
        logger.info("需要询问用户", extra={'tag': 'ROUTING'})
        return "ask_user"
    elif tool_name == "submit_plan_report":
        logger.info("提交最终报告，任务完成", extra={'tag': 'ROUTING'})
        return "finalize"
    else:
        logger.warning(f"未知工具: {tool_name}，重新思考", extra={'tag': 'ROUTING'})
        return "ask_user"


def should_replan(state: PlanState) -> bool:
    """
    判断是否需要重新规划
    
    条件：
    1. 连续失败次数超过阈值
    2. 当前阶段是 executing 但无待处理任务
    3. 执行上下文发生重大变化
    """
    consecutive_failures = state.get("consecutive_failures", 0)
    max_failures = state.get("max_failures", 3)
    current_phase = state.get("current_phase", "")
    
    # 条件1: 连续失败过多
    if consecutive_failures >= max_failures:
        logger.warning(f"连续失败 {consecutive_failures} 次，达到最大阈值 {max_failures}，触发重新规划", 
                       extra={'tag': 'REPLAN_CHECK'})
        return True
    
    # 条件2: 执行阶段但无任务
    if current_phase == "executing" and not state.get("pending_tasks"):
        logger.info("执行阶段但无待处理任务，可能需要重新规划", extra={'tag': 'REPLAN_CHECK'})
        return True
    
    return False


def log_agent_isolation(source_agent: str, target_agent: str, task_description: str, 
                       task_id: str = "", context_isolated: bool = True):
    """
    记录Agent间通信的隔离状态
    
    Args:
        source_agent: 来源Agent名称
        target_agent: 目标Agent名称
        task_description: 任务描述
        task_id: 任务ID
        context_isolated: 是否隔离上下文
    """
    isolation_status = "✅" if context_isolated else "❌"
    
    logger.info(f"Agent 通信隔离状态", extra={'tag': 'AGENT_ISOLATION'})
    logger.info(f"来源Agent: {source_agent} → 目标Agent: {target_agent}", 
               extra={'tag': 'AGENT_ISOLATION'})
    logger.info(f"任务描述: {task_description[:100]}...", extra={'tag': 'AGENT_ISOLATION'})
    logger.info(f"任务ID: {task_id or '未指定'}", extra={'tag': 'AGENT_ISOLATION'})
    logger.info(f"上下文隔离: {isolation_status} {'只传递任务描述，不传递历史消息' if context_isolated else '传递完整上下文'}", 
               extra={'tag': 'AGENT_ISOLATION'})