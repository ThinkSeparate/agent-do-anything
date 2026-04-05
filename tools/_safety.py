# tools/_safety.py
# 安全写入目录配置，供多个工具模块共享

_GET_AGENT_OUTPUT_ROOT = lambda: None


def configure_agent_output_root(getter_func):
    """
    配置安全写入目录根路径的获取方式。
    由 Agent 初始化流程调用。
    """
    global _GET_AGENT_OUTPUT_ROOT
    _GET_AGENT_OUTPUT_ROOT = getter_func


def get_agent_output_root():
    """获取当前配置的安全写入目录根路径。"""
    return _GET_AGENT_OUTPUT_ROOT()
