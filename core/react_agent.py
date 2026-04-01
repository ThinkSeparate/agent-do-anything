# core/react_agent.py
import os
import platform
import logging
from string import Template

from config.configuration import config
from config.prompts import react_system_prompt_template
from core.tool_manager import ToolManager
from core.llm_client import LLMClient
from core.execution_loop import ExecutionLoop
from utils.tools import configure_agent_output_root


class ReActAgent:
    """
    主代理类，负责初始化所有组件并协调工作。
    这是对外的唯一接口，保持与原有调用方式兼容。
    """
    
    def __init__(self, project_directory: str):
        self.logger = logging.getLogger(__name__)
        self.logger.info("ReActAgent 初始化开始", extra={'tag': 'AGENT_INIT'})
        
        self.project_directory = project_directory
        
        # 0. 加载并验证必需配置
        required_keys = ['model.api_key', 'model.base_url', 'model.name', 'agent.output_root']
        config.load(required_keys=required_keys)
        
        # 从配置中读取路径。配置项 `agent.output_root` 可以是绝对路径，也可以是相对于 project_directory 的相对路径。
        self.agent_output_root = self.get_output_root(config.get('agent.output_root'))
        configure_agent_output_root(lambda: self.agent_output_root)
        self.logger.info(f"已从配置加载安全写入目录: {self.agent_output_root}", extra={'tag': 'AGENT_INIT'})
        
        # 1. 初始化工具管理器 (ToolManager 保持纯净，无需修改)
        self.tool_manager = ToolManager()
            
        # 2. 初始化LLM客户端
        self.llm_client = LLMClient(
            model_name=config.get('model.name'),
            base_url=config.get('model.base_url'),
            api_key=config.get('model.api_key')
        )
            
        # 4. 渲染系统提示
        system_prompt = self.render_system_prompt(react_system_prompt_template)
        
        # 5. 初始化执行循环引擎
        self.execution_loop = ExecutionLoop(
            tool_manager=self.tool_manager,
            llm_client=self.llm_client,
            system_prompt=system_prompt
        )
        
        self.logger.info("ReActAgent 初始化完成", extra={'tag': 'AGENT_INIT'})
    
    def run(self, user_input: str) -> str:
        """
        运行代理处理用户输入。
        这是对外的唯一入口，保持与原有接口完全一致。
        
        Args:
            user_input: 用户输入的问题或指令
            
        Returns:
            模型的最终回答文本
        """
        return self.execution_loop.run(user_input)
    
    def render_system_prompt(self, system_prompt_template: str) -> str:
        """渲染系统提示模板，替换变量。"""
        self.logger.debug("开始渲染系统提示模板", extra={'tag': 'PROMPT_RENDER'})
        
        tool_list = self.tool_manager.get_tool_list()
        file_list = ", ".join(
            os.path.abspath(os.path.join(self.project_directory, f))
            for f in os.listdir(self.project_directory)
        )
        agent_output = self.agent_output_root
        
        result = Template(system_prompt_template).substitute(
            operating_system=self.get_operating_system_name(),
            tool_list=tool_list,
            file_list=file_list,
            agent_output=agent_output
        )
        
        self.logger.debug(f"系统提示渲染完成，长度: {len(result)} 字符", 
                         extra={'tag': 'PROMPT_RENDER'})
        return result
    
    def get_output_root(self, output_root):
        output_root_config = config.get('agent.output_root')
        if os.path.isabs(output_root_config):
            agent_output_root = output_root_config
        else:
            # 视为相对于 project_directory 的相对路径
            agent_output_root = os.path.join(self.project_directory, output_root_config)
        # 确保是绝对路径
        return os.path.abspath(agent_output_root)
    
    @staticmethod
    def get_env(env_key) -> str:
        """封装环境变量获取，保持与原有静态方法一致。"""
        return LLMClient.get_env(env_key)
    
    def get_operating_system_name(self):
        """获取操作系统名称。"""
        os_map = {
            "Darwin": "macOS",
            "Windows": "Windows",
            "Linux": "Linux"
        }
        
        system_name = platform.system()
        os_name = os_map.get(system_name, "Unknown")
        self.logger.debug(f"检测到操作系统: {system_name} -> {os_name}", 
                         extra={'tag': 'OS_DETECT'})
        return os_name