# core/compressor/agent.py
import logging
from typing import Dict, Any, List

from langchain.messages import SystemMessage, ToolMessage, AIMessage
from langchain_core.messages import BaseMessage

from config.configuration import config
from core.common.model_define import create_chat_model, bind_tools_to_model
from core.common import agent_utils
from tools.context_compressor_tools import make_compressor_tools
from core.compressor.prompts import system_prompt_template


# 默认消息阈值：低于此值不触发压缩
DEFAULT_MESSAGE_THRESHOLD = 0


class CompressorAgent:
    """上下文压缩Agent，使用手动LLM循环而非LangGraph子图。"""

    def __init__(self, threshold: int = DEFAULT_MESSAGE_THRESHOLD):
        self.logger = logging.getLogger(__name__)
        self.threshold = threshold

        # 加载配置
        agent_utils.load_agent_config(['model.api_key', 'model.base_url', 'model.name', 'model.timeout'])

        # 初始化模型（仅用于压缩决策，不绑定工具）
        self.model = create_chat_model(
            model_name=config.get('model.name'),
            base_url=config.get('model.base_url'),
            api_key=config.get('model.api_key'),
            timeout=config.get('model.timeout'),
        )

        self.logger.info(f"压缩Agent初始化完成，阈值: {self.threshold}", extra={'tag': 'COMPRESSOR_INIT'})

    def compress(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        ReAct图中的compressor节点函数。

        如果消息数低于阈值，返回空dict（无状态变更）。
        否则运行手动Agent循环，返回RemoveMessage+替换消息。

        Args:
            state: 当前AgentState

        Returns:
            状态更新dict，格式 {"messages": [RemoveMessage, ...]}
        """
        messages = state.get("messages", [])

        # 阈值检查
        if len(messages) <= self.threshold:
            self.logger.debug(f"消息数 {len(messages)} <= 阈值 {self.threshold}，跳过压缩",
                            extra={'tag': 'COMPRESSOR_SKIP'})
            return {}

        self.logger.info(f"消息数 {len(messages)} > 阈值 {self.threshold}，开始压缩",
                        extra={'tag': 'COMPRESSOR_START'})

        try:
            # 1. 创建消息深拷贝（每个消息对象独立，但保留相同ID以便add_messages替换）
            import copy
            modified = [copy.deepcopy(msg) for msg in messages]

            # 2. 创建工具（闭包，操作 modified 列表）
            tools = make_compressor_tools(modified)
            tools_by_name = {t.name: t for t in tools}
            model_with_tools = bind_tools_to_model(self.model, tools)

            # 3. 构建压缩Agent的对话上下文
            invoke_messages: List[BaseMessage] = [
                SystemMessage(content=system_prompt_template)
            ] + modified

            # 4. 手动Agent循环
            max_iterations = 50  # 防止无限循环
            for _ in range(max_iterations):
                response = model_with_tools.invoke(invoke_messages)
                invoke_messages.append(response)

                if not response.tool_calls:
                    self.logger.warning("压缩Agent未返回工具调用，异常退出",
                                       extra={'tag': 'COMPRESSOR_WARN'})
                    break

                # 执行所有工具调用
                for tc in response.tool_calls:
                    tool = tools_by_name.get(tc["name"])
                    if tool:
                        result = tool.invoke(tc["args"])
                    else:
                        result = f"未知工具: {tc['name']}"
                    invoke_messages.append(
                        ToolMessage(content=str(result), tool_call_id=tc["id"])
                    )

                # 如果调用了 do_nothing，结束循环
                if any(tc["name"] == "do_nothing" for tc in response.tool_calls):
                    break

            # 5. 对比差异，生成 RemoveMessage + 替换消息
            state_updates = self._build_diff(messages, modified)

            changed_count = len(state_updates.get("messages", []))
            self.logger.info(f"压缩完成，修改了 {changed_count} 条消息",
                           extra={'tag': 'COMPRESSOR_DONE'})

            return state_updates

        except Exception as e:
            self.logger.error(f"压缩过程发生错误: {e}", exc_info=True,
                            extra={'tag': 'COMPRESSOR_ERROR'})
            return {}

    def _build_diff(self, original: list, modified: list) -> Dict[str, Any]:
        """
        对比原始和修改后的消息列表，生成差异状态更新。

        使用 RemoveMessage 删除原始消息，然后添加修改后的新消息。
        add_messages reducer 会正确处理这个顺序。

        Args:
            original: 原始消息列表
            modified: 修改后的消息列表

        Returns:
            {"messages": [RemoveMessage, new_msg, ...]}
        """
        diff_messages = []

        for orig, mod in zip(original, modified):
            if orig.content != mod.content:
                # add_messages reducer: 相同ID的消息会自动替换原始消息
                diff_messages.append(mod)

        return {"messages": diff_messages}