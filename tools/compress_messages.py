# tools/compress_messages.py
from langchain_core.tools import tool
from typing import List, Dict, Any


@tool
def compress_message(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    单条消息压缩。operations每项包含：message_index, operation("clear"/"summarize"), summary_text（summarize时需要）。
    禁止修改索引0（系统消息）和索引1（用户消息）。
    """
    validated_ops = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        msg_idx = op.get("message_index")
        op_type = op.get("operation")
        if msg_idx is None or op_type not in ["clear", "summarize"]:
            continue
        if op_type == "summarize" and not op.get("summary_text", "").strip():
            continue
        validated_ops.append(op)

    return {
        "type": "compress_single_request",
        "operations": validated_ops,
        "message": f"收到 {len(validated_ops)} 条单条压缩操作"
    }


@tool
def compress_paragraph(start_index: int, end_index: int, summary: str) -> Dict[str, Any]:
    """
    段落压缩。消息数>20时才允许使用。将start_index到end_index范围的消息整体总结替换。
    禁止包含索引0（系统消息）和索引1（用户消息）。
    """
    if not isinstance(start_index, int) or not isinstance(end_index, int):
        return {"type": "compress_paragraph_request", "valid": False, "message": "start_index和end_index必须是整数"}
    if not summary or not summary.strip():
        return {"type": "compress_paragraph_request", "valid": False, "message": "summary不能为空"}

    return {
        "type": "compress_paragraph_request",
        "valid": True,
        "start_index": start_index,
        "end_index": end_index,
        "summary": summary.strip()
    }


# 保持向后兼容的别名
compress_messages = compress_message

compress_tools = [compress_message, compress_paragraph]
