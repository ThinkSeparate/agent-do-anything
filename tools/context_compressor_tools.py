# tools/context_compressor_tools.py
from langchain_core.tools import tool
from typing import List


def make_compressor_tools(messages: list) -> List:
    """
    创建压缩工具，闭包捕获消息列表副本。

    Args:
        messages: 消息列表的浅拷贝，工具直接修改此列表中的消息内容

    Returns:
        工具列表 [delete_message_at_index, summarize_message_at_index, do_nothing]
    """

    @tool
    def delete_message_at_index(message_index: int) -> str:
        """清空指定索引的消息内容（保留消息结构和ID，将内容替换为空字符串）。"""
        if 0 <= message_index < len(messages):
            messages[message_index].content = ""
            return f"索引 {message_index} 的消息内容已清空"
        return f"索引 {message_index} 越界，无效操作"

    @tool
    def summarize_message_at_index(message_index: int, summary: str) -> str:
        """将指定索引的消息内容替换为摘要。"""
        if 0 <= message_index < len(messages):
            messages[message_index].content = f"[摘要] {summary}"
            return f"索引 {message_index} 已摘要为: {summary}"
        return f"索引 {message_index} 越界，无效操作"

    @tool
    def do_nothing(reason: str = "无需压缩") -> str:
        """当分析上下文后认为不需要压缩时调用。"""
        return reason

    return [delete_message_at_index, summarize_message_at_index, do_nothing]