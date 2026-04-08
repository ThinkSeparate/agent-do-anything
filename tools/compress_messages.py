# tools/compress_messages.py
from langchain_core.tools import tool
from typing import List, Dict, Any

@tool
def compress_messages(operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    接收压缩策略。
    
    Args:
        operations: 压缩操作列表，每个操作包含：
            - message_index: 要操作的消息索引
            - operation: "delete" 或 "summarize"
            - summary_text: 仅当operation为"summarize"时，摘要文本
    """
    # 只做基本的参数验证
    validated_ops = []
    for op in operations:
        if not isinstance(op, dict):
            continue
            
        msg_idx = op.get("message_index")
        op_type = op.get("operation")
        
        if msg_idx is None or op_type not in ["delete", "summarize"]:
            continue
            
        if op_type == "summarize" and not op.get("summary_text", "").strip():
            continue
            
        validated_ops.append(op)
    
    return {
        "type": "compress_request",
        "operations": validated_ops,
        "message": f"收到 {len(validated_ops)} 条压缩操作，将在tool_node中处理"
    }

compress_tools = [compress_messages]