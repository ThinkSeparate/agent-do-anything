"""用户配置统一管理模块

整合所有用户级配置：
- 任务模式 (task_mode)
- 沙盒策略 (sandbox_policy)
- 其他用户偏好设置
"""

import os
import yaml
from typing import Dict, Any, Optional


class UserProfile:
    """统一用户配置管理器

    所有用户配置集中存储在项目根目录的 user_profile.yaml
    """

    def __init__(self, project_directory: str):
        self.project_dir = project_directory
        self.profile_file = os.path.join(project_directory, "user_profile.yaml")

        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """加载配置"""
        # 尝试加载配置文件
        if os.path.exists(self.profile_file):
            try:
                with open(self.profile_file, 'r', encoding='utf-8') as f:
                    self._data = yaml.safe_load(f) or {}
                return
            except Exception:
                pass

        # 使用默认配置
        self._data = {
            'task_mode': 'short',
            'sandbox_policy': {
                'mode': 'normal',
                'custom_rules': {},
            }
        }
        self.save()

    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self.profile_file, 'w', encoding='utf-8') as f:
                yaml.dump(
                    self._data, f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False
                )
        except Exception as e:
            print(f"⚠️ 保存用户配置失败: {e}")

    # ========== 任务模式 ==========

    @property
    def task_mode(self) -> str:
        """获取任务模式: 'short' 或 'long'"""
        return self._data.get('task_mode', 'short')

    @task_mode.setter
    def task_mode(self, value: str) -> None:
        """设置任务模式"""
        if value in ('short', 'long'):
            self._data['task_mode'] = value
            self.save()

    def toggle_task_mode(self) -> str:
        """切换任务模式，返回新模式"""
        new_mode = 'long' if self.task_mode == 'short' else 'short'
        self.task_mode = new_mode
        return new_mode

    # ========== 沙盒策略 ==========

    @property
    def sandbox_mode(self) -> str:
        """获取沙盒模式"""
        return self._data.get('sandbox_policy', {}).get('mode', 'normal')

    @sandbox_mode.setter
    def sandbox_mode(self, value: str) -> None:
        """设置沙盒模式"""
        if 'sandbox_policy' not in self._data:
            self._data['sandbox_policy'] = {}
        self._data['sandbox_policy']['mode'] = value
        self.save()

    @property
    def sandbox_custom_rules(self) -> Dict:
        """获取沙盒自定义规则"""
        return self._data.get('sandbox_policy', {}).get('custom_rules', {})

    def set_sandbox_custom_rule(self, category: str, command: str, action: str) -> None:
        """设置沙盒自定义规则

        Args:
            category: 命令类别
            command: 命令
            action: 'allow' 或 'deny'
        """
        if 'sandbox_policy' not in self._data:
            self._data['sandbox_policy'] = {}
        if 'custom_rules' not in self._data['sandbox_policy']:
            self._data['sandbox_policy']['custom_rules'] = {}
        if category not in self._data['sandbox_policy']['custom_rules']:
            self._data['sandbox_policy']['custom_rules'][category] = {}

        self._data['sandbox_policy']['custom_rules'][category][command] = action
        self.save()

    def clear_sandbox_custom_rules(self, category: str = None) -> None:
        """清除沙盒自定义规则"""
        if 'sandbox_policy' not in self._data:
            return
        if category:
            self._data['sandbox_policy']['custom_rules'].pop(category, None)
        else:
            self._data['sandbox_policy']['custom_rules'] = {}
        self.save()

    # ========== 通用配置 ==========

    def get(self, key: str, default: Any = None) -> Any:
        """获取任意配置项"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置任意配置项"""
        self._data[key] = value
        self.save()


# 全局实例缓存
_profile_instance: Optional[UserProfile] = None


def get_user_profile(project_directory: str = None) -> UserProfile:
    """获取用户配置实例（单例）"""
    global _profile_instance
    if _profile_instance is None:
        if project_directory is None:
            project_directory = os.getcwd()
        _profile_instance = UserProfile(project_directory)
    return _profile_instance


def reset_user_profile():
    """重置配置实例（用于重新加载）"""
    global _profile_instance
    _profile_instance = None
