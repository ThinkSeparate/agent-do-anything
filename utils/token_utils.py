# utils/token_utils.py
"""
Token 估算工具函数。
"""
from typing import List, Any


def estimate_tokens(text: str) -> int:
    """估算文本的token数量（粗略估算：4字符≈1token）"""
    return len(text) // 4 + 1


def estimate_messages_tokens(messages: List[Any]) -> int:
    """估算消息列表的总token数"""
    total = 0
    for msg in messages:
        content = getattr(msg, 'content', '') or ''
        total += estimate_tokens(content)
        total += 4  # 消息结构开销
    return total
