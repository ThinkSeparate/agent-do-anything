# core/execution_loop.py
import re
import logging
from typing import List, Dict


class ExecutionLoop:
    """
    ReAct 执行循环引擎。
    负责驱动“思考-行动-观察”的循环，并管理连续失败策略。
    """

    def __init__(self, tool_manager, llm_client, action_parser, system_prompt: str):
        self.logger = logging.getLogger(__name__)
        self.tool_manager = tool_manager
        self.llm_client = llm_client
        self.action_parser = action_parser
        self.system_prompt = system_prompt
        
        # 策略上下文跟踪
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3
        
        self.logger.info("ExecutionLoop 初始化完成", extra={'tag': 'EXEC_LOOP_INIT'})

    def run(self, user_input: str) -> str:
        """
        运行主执行循环。
        
        Args:
            user_input: 用户输入的问题
            
        Returns:
            最终的答案文本，或在严重错误时的友好错误信息
        """
        # 记录用户输入
        self.logger.info(f"用户输入: {user_input}", extra={'tag': 'USER_INPUT'})

        # ========== 最终安全网 - 外层异常捕获 ==========
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"<question>{user_input}</question>"}
            ]

            while True:
                # 记录发送给模型的完整消息
                self._log_messages("发送给模型的消息", messages)
                
                # 1. 调用模型获得响应
                content = self.llm_client.call(messages)
                
                # 2. 检测 Thought
                thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
                if thought_match:
                    thought = thought_match.group(1)
                    self.logger.info(f"Thought: {thought}", extra={'tag': 'THOUGHT'})

                # 3. 检测模型是否输出 Final Answer
                if "<final_answer>" in content:
                    final_answer = re.search(r"<final_answer>(.*?)</final_answer>", content, re.DOTALL)
                    final_answer_text = final_answer.group(1)
                    self.logger.info(f"模型输出最终答案", extra={'tag': 'FINAL_ANSWER'})
                    self.logger.info(f"最终答案内容: {final_answer_text}", extra={'tag': 'FINAL_ANSWER'})
                    return final_answer_text

                # 4. 检测 Action
                action_match = re.search(r"<action>(.*?)</action>", content, re.DOTALL)
                if not action_match:
                    error_msg = "模型未输出 <action> 标签"
                    self.logger.error(error_msg, extra={'tag': 'ERROR'})
                    raise RuntimeError(error_msg)
                
                action = action_match.group(1)
                
                # 5. 解析 Action
                try:
                    tool_name, args = self.action_parser.parse(action)
                except ValueError as e:
                    error_msg = f"动作解析失败: {e}"
                    self.logger.error(error_msg, extra={'tag': 'ERROR'})
                    # 将解析错误作为观察反馈给模型
                    observation = f"动作解析失败: {e}。请确保使用正确的函数调用语法，如：tool_name(arg1, arg2)。"
                    messages.append({"role": "user", "content": f"<observation>{observation}</observation>"})
                    continue
                
                self.logger.info(f"解析到工具调用: {tool_name}", extra={'tag': 'ACTION_PARSE'})
                self.logger.info(f"工具参数: {args}", extra={'tag': 'ACTION_PARSE'})
                
                # 6. 执行前检查（如终端命令确认）
                if tool_name == "run_terminal_command":
                    self.logger.warning(f"即将执行终端命令: {args[0] if args else '无参数'}", 
                                      extra={'tag': 'TERMINAL_WARNING'})
                    should_continue = input(f"\n⚠️  即将执行终端命令: {args[0] if args else '无参数'}\n是否继续？（Y/N）")
                    if should_continue.lower() != 'y':
                        self.logger.warning("用户取消了终端命令执行", extra={'tag': 'USER_CANCEL'})
                        print("\n操作已取消。")
                        return "操作被用户取消"
                else:
                    self.logger.info(f"执行工具: {tool_name}", extra={'tag': 'TOOL_EXECUTION'})

                # 7. 执行工具并处理结果
                try:
                    observation = self.tool_manager.execute_tool(tool_name, args)
                    # 工具成功，重置连续失败计数器
                    self._consecutive_failures = 0
                    
                except KeyError as e:
                    # 工具不存在的情况
                    error_msg = str(e)
                    self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
                    observation = f"工具“{tool_name}”不存在。请从可用工具列表中选择：{list(self.tool_manager.tools.keys())}"
                    # 增加连续失败计数
                    self._consecutive_failures += 1
                    
                except Exception as e:
                    # 工具执行出错的情况
                    error_msg = f"工具 '{tool_name}' 执行失败。参数: {args}。错误详情: {e}"
                    self.logger.error(error_msg, extra={'tag': 'TOOL_ERROR'})
                    observation = f"执行工具 {tool_name} 时出错: {e}。请检查参数是否正确，或尝试其他方法。"
                    
                    # ===== 策略上下文逻辑 =====
                    # 1. 增加连续失败计数
                    self._consecutive_failures += 1
                    
                    # 2. 判断是否达到连续失败阈值
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        # 达到阈值，构建强引导恢复提示
                        recovery_prompt = (
                            f"\n[系统提示] 注意：当前步骤已连续失败 {self._consecutive_failures} 次。最后的错误是：{str(e)[:100]}。\n"
                            f"你必须立即停止当前方法，在 <thought> 中彻底分析失败原因，并尝试一个完全不同的新策略。\n"
                            f"如果无法继续，请使用 <final_answer> 报告遇到的阻塞。"
                        )
                        # 将恢复提示作为一条用户消息插入，引导下一轮模型思考
                        messages.append({"role": "user", "content": recovery_prompt})
                        self.logger.warning(f"已注入恢复提示，引导模型调整策略。", extra={'tag': 'STRATEGY_SHIFT'})
                        
                        # 重置计数器，并跳过将本次失败观察加入历史，直接进入下一轮循环
                        self._consecutive_failures = 0
                        continue
                
                # 8. 将观察结果加入消息历史，继续循环
                obs_msg = f"<observation>{observation}</observation>"
                messages.append({"role": "user", "content": obs_msg})
                # 记录添加到消息历史中的观察结果
                self.logger.debug(f"添加到消息历史的观察: {observation[:200]}...", 
                                extra={'tag': 'OBSERVATION_ADDED'})
                
        # ========== 最终安全网 - 异常处理块 ==========
        except Exception as e:
            # 捕获所有未处理的异常（如RuntimeError, 模型API错误等）
            self.logger.critical(f"任务执行过程中发生未捕获的异常: {e}", exc_info=True, extra={'tag': 'TASK_CRASH'})
            # 返回对用户友好的错误信息，而不是让程序崩溃
            return f"任务执行过程发生意外错误，已终止。错误类型：{type(e).__name__}"

    def _log_messages(self, title: str, messages: list):
        """记录消息列表的辅助方法。"""
        self.logger.info(f"=== {title} ===", extra={'tag': 'MESSAGES'})
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            # 截断过长的内容以便阅读
            content_preview = content[:300] + "..." if len(content) > 300 else content
            
            self.logger.info(f"[消息 {i}] 角色: {role}", extra={'tag': 'MESSAGES'})
            self.logger.debug(f"内容预览:\n{content_preview}", extra={'tag': 'MESSAGES_DETAIL'})
            
            # 如果是系统提示，记录完整内容到调试日志
            if role == 'system':
                self.logger.debug(f"系统提示完整内容:\n{content}", extra={'tag': 'SYSTEM_PROMPT'})
        
        self.logger.info(f"=== {title} 结束 ===", extra={'tag': 'MESSAGES'})