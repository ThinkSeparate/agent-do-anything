# core/execution_loop.py
import re
import logging
from typing import List, Dict


class ExecutionLoop:
    """
    ReAct 执行循环引擎。
    负责驱动“思考-行动-观察”的循环，并管理连续失败策略。
    """

    def __init__(self, tool_manager, llm_client, system_prompt: str):
        self.logger = logging.getLogger(__name__)
        self.tool_manager = tool_manager
        self.llm_client = llm_client
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

                # 将模型的完整响应作为 assistant 消息追加到历史中（新增关键步骤）
                messages.append({"role": "assistant", "content": content})
                
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
                
                # 5. 执行 Action（通过ToolManager的完整处理流程）
                action_result = self.tool_manager.handle_action(action)
                
                # 6. 根据结构化的结果判断是否失败
                is_failure = not action_result.get("success", False)
                # 无论是结果还是错误信息，都作为观察内容
                raw_observation = action_result.get("data")

                if isinstance(raw_observation, dict):
                    # 如果是结构化结果，提取其中的 'data' 字段作为主要信息
                    observation = raw_observation.get('data', str(raw_observation))
                    # 可以选择性地记录其他字段，如 returncode
                    if 'returncode' in raw_observation:
                        self.logger.debug(f"命令返回码: {raw_observation['returncode']}")
                else:
                    # 如果不是字典，保持原样（兼容旧格式或错误信息）
                    observation = str(raw_observation)

                if is_failure:
                    self._consecutive_failures += 1
                    self.logger.warning(f"动作执行失败，连续失败计数: {self._consecutive_failures}", 
                                      extra={'tag': 'CONSECUTIVE_FAIL'})
                    
                    # 判断是否达到连续失败阈值
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        recovery_prompt = (
                            f"\n[系统提示] 注意：当前步骤已连续失败 {self._consecutive_failures} 次。最后的错误是：{observation[:100]}。\n"
                            f"你必须立即停止当前方法，在 <thought> 中彻底分析失败原因，并尝试一个完全不同的新策略。\n"
                            f"如果无法继续，请使用 <final_answer> 报告遇到的阻塞。"
                        )
                        messages.append({"role": "user", "content": recovery_prompt})
                        self.logger.warning("已注入恢复提示，引导模型调整策略。", 
                                          extra={'tag': 'STRATEGY_SHIFT'})
                        self._consecutive_failures = 0
                        continue
                else:
                    self._consecutive_failures = 0
                
                # 7. 将观察结果加入消息历史，继续循环
                obs_msg = f"<observation>{observation}</observation>"
                messages.append({"role": "user", "content": obs_msg})
                self.logger.debug(f"添加到消息历史的观察: {observation}...", 
                                extra={'tag': 'OBSERVATION_ADDED'})
                
        # ========== 最终安全网 - 异常处理块 ==========
        except Exception as e:
            # 捕获所有未处理的异常（如RuntimeError, 模型API错误等）
            self.logger.critical(f"任务执行过程中发生未捕获的异常: {e}", exc_info=True, 
                               extra={'tag': 'TASK_CRASH'})
            return f"任务执行过程发生意外错误，已终止。错误类型：{type(e).__name__}"

    def _log_messages(self, title: str, messages: list):
        """记录消息列表的辅助方法。"""
        self.logger.info(f"=== {title} ===", extra={'tag': 'MESSAGES'})
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')            
            self.logger.info(f"[消息 {i}] 角色: {role}", extra={'tag': 'MESSAGES'})

        self.logger.debug(f"发给模型的完整信息:\n{messages}", extra={'tag': 'MESSAGES_DETAIL'})

        self.logger.info(f"=== {title} 结束 ===", extra={'tag': 'MESSAGES'})