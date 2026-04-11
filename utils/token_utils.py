# utils/token_utils.py
"""
Token 估算工具函数 - 根据模型类型选择计算方法
"""
from typing import List, Any, Optional
import json
import re

# 尝试导入 tiktoken
try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


# 全局变量
_tools_token_count: int = 0
_model_name: str = ""
_tools_list: List[Any] = []


def set_model_name(name: str):
    """设置当前模型名称"""
    global _model_name
    _model_name = name


def get_model_name() -> str:
    """获取当前模型名称"""
    return _model_name


def set_tools_token_count(count: int):
    """设置工具定义的 token 数量"""
    global _tools_token_count
    _tools_token_count = count


def get_tools_token_count() -> int:
    """获取工具定义的 token 数量"""
    return _tools_token_count


def set_tools_list(tools: List[Any]):
    """设置工具列表（用于构造 API 请求）"""
    global _tools_list
    _tools_list = tools


def get_tools_list() -> List[Any]:
    """获取工具列表"""
    return _tools_list


def get_tools_for_api() -> List[dict]:
    """
    获取工具定义，格式化为 API 请求格式

    返回 OpenAI 格式的工具定义列表：
    [{"type": "function", "function": {...}}, ...]
    """
    tools = []
    for tool in _tools_list:
        tool_def = {"type": "function", "function": {}}

        # 基本信息
        tool_def["function"]["name"] = getattr(tool, 'name', '')
        tool_def["function"]["description"] = getattr(tool, 'description', '')

        # 参数 schema
        args_schema = getattr(tool, 'args_schema', None)
        if args_schema:
            try:
                if hasattr(args_schema, 'model_json_schema'):
                    schema_dict = args_schema.model_json_schema()
                elif hasattr(args_schema, 'schema'):
                    schema_dict = args_schema.schema()
                else:
                    schema_dict = {}

                # 清理 schema（移除 title 等不必要的字段）
                if 'title' in schema_dict:
                    del schema_dict['title']

                tool_def["function"]["parameters"] = schema_dict
            except Exception:
                tool_def["function"]["parameters"] = {"type": "object", "properties": {}}
        else:
            tool_def["function"]["parameters"] = {"type": "object", "properties": {}}

        tools.append(tool_def)

    return tools


def is_deepseek_model() -> bool:
    """检查是否是 DeepSeek 模型"""
    return "deepseek" in _model_name.lower()


def count_chinese_chars(text: str) -> int:
    """计算中文字符数量"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def get_tiktoken_encoding():
    """获取 tiktoken 编码器"""
    if not _TIKTOKEN_AVAILABLE:
        return None
    try:
        # 根据模型选择 encoding
        if "gpt-4o" in _model_name.lower():
            return tiktoken.get_encoding("o200k_base")
        else:
            # GPT-4, GPT-3.5-turbo, text-embedding-ada-002
            return tiktoken.get_encoding("cl100k_base")
    except:
        return None


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量

    策略：
    - DeepSeek：中文 1:1，英文 4:1（基于实际观察）
    - OpenAI 模型：使用 tiktoken
    """
    if not text:
        return 0

    # DeepSeek 使用基于字符的估算
    if is_deepseek_model():
        chinese = count_chinese_chars(text)
        non_chinese = len(text) - chinese
        return chinese + (non_chinese // 4) + 1

    # OpenAI 模型使用 tiktoken
    enc = get_tiktoken_encoding()
    if enc:
        return len(enc.encode(text))

    # 默认：4字符≈1token
    return len(text) // 4 + 1


def estimate_tool_definition_tokens(tool: Any) -> int:
    """
    估算单个工具定义的 token 数量

    包括：
    - name
    - description
    - parameters (JSON Schema)
    """
    total = 0

    # 工具名
    name = getattr(tool, 'name', '')
    total += estimate_tokens(name)

    # 描述
    description = getattr(tool, 'description', '')
    total += estimate_tokens(description)

    # 参数 schema
    args_schema = getattr(tool, 'args_schema', None)
    if args_schema:
        try:
            # Pydantic 模型转 JSON
            if hasattr(args_schema, 'model_json_schema'):
                schema_dict = args_schema.model_json_schema()
            elif hasattr(args_schema, 'schema'):
                schema_dict = args_schema.schema()
            else:
                schema_dict = {}

            schema_str = json.dumps(schema_dict, ensure_ascii=False)
            total += estimate_tokens(schema_str)
        except Exception:
            # 估算失败时给个默认值
            total += 200

    # 结构开销
    total += 20

    return total


def calculate_tools_token_count(tools: List[Any]) -> int:
    """
    计算工具列表的总 token 数量

    在 agent 初始化时调用一次，然后调用 set_tools_token_count()
    """
    total = 0
    for tool in tools:
        total += estimate_tool_definition_tokens(tool)

    # 额外开销（系统提示等）
    total += 500

    return total


def estimate_tool_calls_tokens(tool_calls: List[Any]) -> int:
    """估算 tool_calls 的 token 数量"""
    if not tool_calls:
        return 0

    total = 0
    for tc in tool_calls:
        if isinstance(tc, dict):
            # 估算 name + id + args 的 token
            name = tc.get('name', '')
            tc_id = tc.get('id', '')
            args = tc.get('args', {})

            total += estimate_tokens(name)
            total += estimate_tokens(tc_id)
            # args 转为 JSON 估算
            try:
                args_str = json.dumps(args, ensure_ascii=False)
                total += estimate_tokens(args_str)
            except:
                total += 50  # 默认值

            total += 10  # 结构开销
        else:
            total += 50  # 默认值

    return total


def estimate_messages_tokens(messages: List[Any]) -> int:
    """
    估算消息列表的总 token 数（基于完整 API 请求体格式）

    构造与 API 请求完全一致的格式，然后计算 token：
    - messages: 转换为 API 格式（含 role, content, tool_calls 等）
    - tools: 工具定义
    """
    try:
        from langchain_core.messages import message_to_dict

        # 构造完整 API 请求体
        api_request = {
            "messages": [message_to_dict(m) for m in messages],
            "tools": get_tools_for_api(),
        }

        # 将请求体转为 JSON 字符串计算 token
        request_str = json.dumps(api_request, ensure_ascii=False)

        # 使用对应的方法计算 token
        if is_deepseek_model():
            # DeepSeek：中文 1:1，英文 4:1
            chinese = count_chinese_chars(request_str)
            non_chinese = len(request_str) - chinese
            total = chinese + (non_chinese // 4) + 1
        else:
            # OpenAI：使用 tiktoken
            enc = get_tiktoken_encoding()
            if enc:
                total = len(enc.encode(request_str))
            else:
                total = len(request_str) // 4 + 1

        return total

    except Exception:
        # 失败时回退到简单估算
        total = 0
        for msg in messages:
            total += 3  # 消息开销
            content = getattr(msg, 'content', '') or ''
            total += estimate_tokens(content)

            tool_calls = getattr(msg, 'tool_calls', None)
            if tool_calls:
                total += estimate_tool_calls_tokens(tool_calls)

            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id:
                total += estimate_tokens(str(tool_call_id)) + 5

        total += get_tools_token_count()
        return total


def estimate_total_request_tokens(
    messages: List[Any],
    system_prompt: str = "",
    tools: Optional[List[Any]] = None
) -> int:
    """
    估算完整请求的总 token 数（用于精确截断判断）

    包括：
    - System Prompt
    - 所有消息
    - 工具定义
    - API 格式开销
    """
    total = 0

    # System Prompt
    if system_prompt:
        total += estimate_tokens(system_prompt)
        total += 3  # 消息格式开销

    # 所有消息
    total += estimate_messages_tokens(messages)

    # 工具定义
    if tools:
        total += calculate_tools_token_count(tools)
    else:
        total += get_tools_token_count()

    # API 额外开销
    total += 10

    return total
