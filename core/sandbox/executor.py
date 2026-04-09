"""命令行沙盒执行器 - 提供安全的命令执行环境"""

import fnmatch
import logging
import os
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import psutil
import yaml


class SafetyLevel(Enum):
    """安全级别"""
    SAFE = "safe"          # 安全，自动执行
    CAUTION = "caution"    # 需注意，根据模式决定
    DANGEROUS = "dangerous"  # 危险，通常需要确认


@dataclass
class CommandPolicy:
    """命令策略"""
    category: str
    auto_execute: bool
    require_confirm: bool


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    stdout: str
    stderr: str
    returncode: int
    execution_time: float
    was_cancelled: bool = False


class SandboxExecutor:
    """
    沙盒命令执行器

    功能：
    1. 基于策略的命令分类和授权
    2. 超时控制
    3. 目录限制
    4. 资源监控
    """

    def __init__(self, project_directory: str, policy_file: str = None):
        self.logger = logging.getLogger(__name__)
        self.project_directory = os.path.abspath(project_directory)

        # 加载策略
        if policy_file is None:
            policy_file = os.path.join(
                os.path.dirname(__file__), '..', '..', 'config', 'sandbox_policy.yaml'
            )
        self.policy = self._load_policy(policy_file)

        # 初始化命令策略映射
        self.command_policies = self._build_command_policies()

        self.logger.info(f"沙盒执行器初始化，模式: {self.policy.get('mode', 'normal')}")

    def _load_policy(self, policy_file: str) -> dict:
        """加载策略配置文件"""
        try:
            with open(policy_file, 'r', encoding='utf-8') as f:
                policy = yaml.safe_load(f)

            # 替换变量
            self._expand_policy_variables(policy)
            return policy
        except Exception as e:
            self.logger.error(f"加载沙盒策略失败: {e}")
            return {'mode': 'normal', 'command_policies': {}}

    def _expand_policy_variables(self, policy: dict):
        """展开策略中的变量"""
        project_dir = self.project_directory

        def expand_value(value):
            if isinstance(value, str):
                return value.replace('${PROJECT_DIR}', project_dir)
            elif isinstance(value, list):
                return [expand_value(v) for v in value]
            elif isinstance(value, dict):
                return {k: expand_value(v) for k, v in value.items()}
            return value

        for key in ['allowed_directories', 'forbidden_directories', 'unattended_whitelist']:
            if key in policy:
                policy[key] = expand_value(policy[key])

    def _build_command_policies(self) -> dict:
        """构建命令策略映射表（从YAML command_categories读取，并应用用户定制）"""
        policies = {}
        mode = self.policy.get('mode', 'normal')
        categories = self.policy.get('command_categories', {})
        custom_rules = self.policy.get('custom_rules', {})

        for cat_key, cat_config in categories.items():
            # 根据当前模式确定允许的命令（严格 ⊂ 标准 ⊂ 宽松）
            strict_cmds = set(cat_config.get('strict', []))
            normal_cmds = strict_cmds | set(cat_config.get('normal', []))
            permissive_cmds = normal_cmds | set(cat_config.get('permissive', []))
            forbidden = set(cat_config.get('forbidden', []))

            if mode == 'strict':
                allowed = strict_cmds
            elif mode == 'normal':
                allowed = normal_cmds
            else:  # permissive
                allowed = permissive_cmds

            # 应用用户定制
            cat_custom = custom_rules.get(cat_key, {})
            for cmd, rule in cat_custom.items():
                if rule == 'allow':
                    allowed.add(cmd)
                elif rule == 'deny':
                    allowed.discard(cmd)
                    forbidden.add(cmd)

            # 为每个命令创建策略
            all_cmds = strict_cmds | normal_cmds | permissive_cmds | set(cat_custom.keys())
            for cmd in all_cmds:
                if cmd in forbidden:
                    policies[cmd] = CommandPolicy(
                        category=cat_key,
                        auto_execute=False,
                        require_confirm=True
                    )
                elif cmd in allowed:
                    policies[cmd] = CommandPolicy(
                        category=cat_key,
                        auto_execute=True,
                        require_confirm=False
                    )
                else:
                    policies[cmd] = CommandPolicy(
                        category=cat_key,
                        auto_execute=False,
                        require_confirm=True
                    )

        return policies

    def _match_command(self, user_cmd: str, policy_cmd: str) -> bool:
        """
        匹配用户命令与策略命令（支持通配符和前缀匹配）

        匹配规则（优先级从高到低）：
        1. 完全相等
        2. 通配符匹配（*.py 匹配 script.py）
        3. 前缀匹配（python 匹配 python script.py）
        """
        user_lower = user_cmd.lower().strip()
        policy_lower = policy_cmd.lower().strip()

        # 1. 完全相等
        if user_lower == policy_lower:
            return True

        # 2. 通配符匹配
        if '*' in policy_lower:
            pattern = policy_lower.replace('*', '.*')
            if re.match(f'^{pattern}$', user_lower):
                return True

        # 3. 前缀匹配（无参策略匹配带参命令）
        # 策略 "python" 可以匹配 "python script.py"
        if ' ' not in policy_lower:  # 无参策略
            if user_lower.startswith(policy_lower + ' '):
                return True

        return False

    def analyze_command(self, command: str) -> Tuple[SafetyLevel, str]:
        """
        分析命令的安全级别

        Returns:
            (安全级别, 原因说明)
        """
        cmd_lower = command.lower().strip()

        # 检查危险模式（优先检查）
        dangerous_patterns = [
            r'rm\s+-rf\s+/',
            r'format\s+[a-z]:',
            r'dd\s+if=.*of=/dev/',
            r'mkfs',
            r'>\s*/dev/',
            r'.*\|\s*sh',
            r'.*\|\s*bash',
            r'curl.*\|\s*sh',
            r'wget.*\|\s*sh',
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, cmd_lower):
                return SafetyLevel.DANGEROUS, f"匹配危险模式: {pattern}"

        # 检查完整命令是否在策略中（优先匹配更长的命令）
        matched_policy = None
        matched_cmd = None
        # 按策略长度降序排序，长的优先匹配
        sorted_policies = sorted(self.command_policies.items(), key=lambda x: len(x[0]), reverse=True)
        for cmd_pattern, policy in sorted_policies:
            if self._match_command(cmd_lower, cmd_pattern):
                matched_policy = policy
                matched_cmd = cmd_pattern
                break  # 找到最长的匹配就停止

        if matched_policy:
            if matched_policy.require_confirm and not matched_policy.auto_execute:
                return SafetyLevel.DANGEROUS, f"{matched_cmd} 被分类为禁止"
            elif matched_policy.require_confirm:
                return SafetyLevel.CAUTION, f"{matched_cmd} 在当前模式下需要确认"
            else:
                return SafetyLevel.SAFE, f"{matched_cmd} 允许自动执行"

        # 提取主要命令作为备选
        base_cmd = cmd_lower.split()[0] if cmd_lower else ''

        # 未知命令，保守处理
        return SafetyLevel.CAUTION, f"未知命令 '{base_cmd}'，需要确认"

    def check_directory_allowed(self, command: str) -> Tuple[bool, str]:
        """
        检查命令是否在允许的目录范围内

        Returns:
            (是否允许, 原因)
        """
        allowed_dirs = self.policy.get('allowed_directories', [])
        forbidden_dirs = self.policy.get('forbidden_directories', [])

        # 如果没有配置目录限制，允许所有
        if not allowed_dirs and not forbidden_dirs:
            return True, "未配置目录限制"

        # 提取命令中的路径参数
        paths = self._extract_paths_from_command(command)

        for path in paths:
            abs_path = os.path.abspath(path)

            # 检查禁止目录
            for forbidden in forbidden_dirs:
                if abs_path.startswith(os.path.abspath(forbidden)):
                    return False, f"路径 '{path}' 在禁止目录 '{forbidden}' 中"

            # 检查允许目录（如果配置了）
            if allowed_dirs:
                in_allowed = False
                for allowed in allowed_dirs:
                    if abs_path.startswith(os.path.abspath(allowed)):
                        in_allowed = True
                        break
                if not in_allowed:
                    return False, f"路径 '{path}' 不在允许的目录范围内"

        return True, "目录检查通过"

    def _extract_paths_from_command(self, command: str) -> List[str]:
        """从命令中提取路径参数"""
        paths = []
        # 简单的路径匹配：查找看起来像路径的参数
        tokens = command.split()
        for token in tokens:
            # 跳过选项参数
            if token.startswith('-'):
                continue
            # 可能是路径的特征
            if '/' in token or '\\' in token or ':' in token:
                # 清理引号
                clean_path = token.strip('"\'')
                paths.append(clean_path)
        return paths

    def check_whitelist(self, command: str) -> bool:
        """检查命令是否在无人值守白名单中"""
        whitelist = self.policy.get('unattended_whitelist', [])
        if not whitelist:
            return False

        cmd_lower = command.lower().strip()
        for pattern in whitelist:
            if fnmatch.fnmatch(cmd_lower, pattern.lower()):
                return True
        return False

    def should_confirm(self, command: str) -> Tuple[bool, str]:
        """
        判断是否需要用户确认

        Returns:
            (是否需要确认, 原因)
        """
        mode = self.policy.get('mode', 'normal')

        # 无人值守模式：检查白名单
        if mode == 'unattended':
            if self.check_whitelist(command):
                return False, "在白名单中，无人值守模式自动执行"
            else:
                return True, "不在白名单中，需要确认"

        # 分析命令安全级别
        safety, reason = self.analyze_command(command)

        if safety == SafetyLevel.DANGEROUS:
            return True, f"危险命令: {reason}"
        elif safety == SafetyLevel.CAUTION:
            return True, f"需注意: {reason}"

        # 目录检查
        dir_allowed, dir_reason = self.check_directory_allowed(command)
        if not dir_allowed:
            return True, f"目录限制: {dir_reason}"

        return False, "安全检查通过，自动执行"

    def execute(self, command: str, timeout: int = None, confirm_callback=None) -> ExecutionResult:
        """
        执行命令

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒），None表示使用策略配置
            confirm_callback: 确认回调函数，返回bool

        Returns:
            ExecutionResult
        """
        start_time = time.time()

        # 检查是否需要确认
        need_confirm, reason = self.should_confirm(command)

        if need_confirm:
            self.logger.info(f"命令需要确认: {reason}")

            if confirm_callback:
                if not confirm_callback(command, reason):
                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr=f"用户取消执行: {reason}",
                        returncode=-1,
                        execution_time=0,
                        was_cancelled=True
                    )
            else:
                # 默认交互式确认
                print(f"\n⚠️  {reason}")
                print(f"命令: {command}")
                response = input("是否执行？(Y/n): ").strip().lower()
                if response and response != 'y':
                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr="用户取消执行",
                        returncode=-1,
                        execution_time=0,
                        was_cancelled=True
                    )

        # 确定超时时间
        if timeout is None:
            timeout = self.policy.get('timeouts', {}).get('default', 30)

        # 执行命令
        return self._execute_with_timeout(command, timeout, start_time)

    def _execute_with_timeout(self, command: str, timeout: int, start_time: float) -> ExecutionResult:
        """带超时控制的命令执行"""
        try:
            # 使用subprocess执行
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )

            # 资源监控
            def monitor_resources():
                try:
                    p = psutil.Process(process.pid)
                    max_memory = 0
                    max_cpu = 0

                    while process.poll() is None:
                        try:
                            mem = p.memory_info().rss / 1024 / 1024  # MB
                            cpu = p.cpu_percent(interval=0.1)
                            max_memory = max(max_memory, mem)
                            max_cpu = max(max_cpu, cpu)

                            # 检查资源限制
                            limits = self.policy.get('resource_limits', {})
                            if limits.get('max_memory_mb') and max_memory > limits['max_memory_mb']:
                                self.logger.warning(f"内存超限: {max_memory}MB > {limits['max_memory_mb']}MB")
                                process.terminate()
                                break
                        except:
                            break

                        time.sleep(0.5)
                except:
                    pass

            # 启动资源监控线程
            monitor_thread = threading.Thread(target=monitor_resources)
            monitor_thread.daemon = True
            monitor_thread.start()

            # 等待执行完成或超时
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                execution_time = time.time() - start_time

                return ExecutionResult(
                    success=process.returncode == 0,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=process.returncode,
                    execution_time=execution_time
                )
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                execution_time = time.time() - start_time

                return ExecutionResult(
                    success=False,
                    stdout=stdout,
                    stderr=f"命令执行超时（{timeout}秒）",
                    returncode=-1,
                    execution_time=execution_time
                )

        except Exception as e:
            execution_time = time.time() - start_time
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"执行异常: {str(e)}",
                returncode=-1,
                execution_time=execution_time
            )


# 全局执行器实例
_sandbox_executor = None


def get_sandbox_executor(project_directory: str = None) -> SandboxExecutor:
    """获取沙盒执行器实例"""
    global _sandbox_executor
    if _sandbox_executor is None:
        if project_directory is None:
            project_directory = os.getcwd()
        _sandbox_executor = SandboxExecutor(project_directory)
    return _sandbox_executor


def reset_sandbox_executor():
    """重置执行器实例（用于重新加载配置）"""
    global _sandbox_executor
    _sandbox_executor = None
