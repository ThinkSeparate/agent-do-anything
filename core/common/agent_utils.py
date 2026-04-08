# core/common/agent_utils.py
import os
import platform
import logging
from typing import List, Callable, Optional
from string import Template

from config.configuration import config
from core.common.model_define import create_chat_model, bind_tools_to_model
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# ========== 配置与模型 ==========
def load_agent_config(required_keys: List[str]) -> None:
    """
    加载 Agent 必需配置项。
    
    Args:
        required_keys: 必需配置键列表，例如：
            ['model.api_key', 'model.base_url', 'model.name', 'model.timeout']
    """
    config.load(required_keys=required_keys)
    logger.debug(f"配置加载完成，必需键: {required_keys}", extra={'tag': 'CONFIG_LOAD'})


def create_agent_model(
    model_keys: dict,
    tools_getter: Optional[Callable] = None
):
    """
    创建 Agent 模型，可选择绑定工具。
    
    Args:
        model_keys: 模型配置键字典，包含：
            - model_name: 模型名称
            - base_url: API基础URL
            - api_key: API密钥
            - timeout: 超时时间
        tools_getter: 工具获取函数，返回工具列表。若为 None 则不绑定工具。
    
    Returns:
        模型实例（已绑定工具如果提供了 tools_getter）
    """
    # 创建基础模型
    model = create_chat_model(
        model_name=model_keys.get('model_name'),
        base_url=model_keys.get('base_url'),
        api_key=model_keys.get('api_key'),
        timeout=model_keys.get('timeout'),
    )
    
    # 绑定工具（如果有）
    if tools_getter is not None:
        tools = tools_getter()
        model = bind_tools_to_model(model, tools)
        logger.debug(f"模型已绑定 {len(tools)} 个工具", extra={'tag': 'MODEL_INIT'})
    
    return model


# ========== 系统提示渲染 ==========
def render_system_prompt(
    template: str,
    project_directory: str,
    additional_vars: Optional[dict] = None
) -> str:
    """
    渲染系统提示模板，统一处理公共变量替换。
    
    Args:
        template: 模板字符串
        project_directory: 项目目录路径
        additional_vars: 额外的模板变量字典
    
    Returns:
        渲染后的提示字符串
    """
    # 获取文件列表
    try:
        files = os.listdir(project_directory)
        if len(files) > 10:
            file_list = ", ".join(files[:10]) + f" 等 {len(files)} 个文件"
        else:
            file_list = ", ".join(files)
    except Exception as e:
        logger.warning(f"无法读取项目目录文件列表: {e}", extra={'tag': 'PROMPT_RENDER'})
        file_list = "无法读取目录"
    
    # 操作系统信息
    os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
    system_name = platform.system()
    os_name = os_map.get(system_name, "Unknown")
    
    # 基础变量
    base_vars = {
        "operating_system": os_name,
        "working_directory": project_directory,
        "file_list": file_list,
    }
    
    # 合并额外变量
    if additional_vars:
        base_vars.update(additional_vars)
    
    # 渲染模板
    return Template(template).substitute(**base_vars)


# ========== 路径处理 ==========
def get_agent_output_root(output_root_config: str, project_directory: str) -> str:
    """
    获取 Agent 输出根目录（绝对路径）。
    
    Args:
        output_root_config: 配置中的输出路径
        project_directory: 项目目录
    
    Returns:
        绝对路径
    """
    if os.path.isabs(output_root_config):
        agent_output_root = output_root_config
    else:
        agent_output_root = os.path.join(project_directory, output_root_config)
    return os.path.abspath(agent_output_root)