# core/clarify/model_node.py
# 可以完全复用 `core/react/model_node.py` 的 `create_react_model_node` 函数逻辑。
# 为了清晰，可以创建一个简单的包装函数，或者直接导入。
from core.react.model_node import create_react_model_node as create_base_model_node

# 直接复用，或者如果需要不同的日志标签，可以稍作修改
def create_clarify_model_node(model_with_tools, system_prompt: str):
    """创建用于需求澄清的模型节点。"""
    base_node = create_base_model_node(model_with_tools, system_prompt)
    # 可以在这里对base_node返回的函数进行装饰，以更改日志标签等，但非必需。
    return base_node