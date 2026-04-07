# tools/integrated_compression_tool.py
import logging

_COMPRESSOR_AGENT = None


def get_compressor_agent():
    """获取或创建全局压缩Agent实例（懒加载单例）。"""
    global _COMPRESSOR_AGENT
    if _COMPRESSOR_AGENT is None:
        from core.compressor.agent import CompressorAgent
        _COMPRESSOR_AGENT = CompressorAgent()
        logging.getLogger(__name__).info("全局压缩Agent实例已创建", extra={'tag': 'COMPRESSOR_TOOL'})
    return _COMPRESSOR_AGENT


def invoke_context_compressor(state):
    """
    ReAct图中的compressor节点。

    如果消息数低于阈值，返回空dict。
    否则调用CompressorAgent进行压缩，返回差异状态更新。
    """
    return get_compressor_agent().compress(state)