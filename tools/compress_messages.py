# tools/compress_messages.py
from langchain_core.tools import tool
from typing import List, Dict, Any


@tool
def compress_messages(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    单条消息压缩。operations每项包含：index, operation("clear"/"summarize"), summary_text（summarize时需要）。
    禁止修改index:1（用户初始任务）。
    """
    validated_ops = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        msg_idx = op.get("index")
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


compress_tools = [compress_messages]
