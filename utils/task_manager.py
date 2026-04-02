# utils/task_manager.py
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import logging

class TaskManager:
    """
    任务管理器，简化版交互流程
    """
    
    def __init__(self, project_directory: str, history_file: str = "task_history.json"):
        """
        初始化任务管理器
        
        Args:
            project_directory: 项目目录路径
            history_file: 任务历史文件名
        """
        self.project_dir = project_directory
        self.history_file = history_file
        self.history_path = os.path.join(project_directory, history_file)
        self.logger = logging.getLogger(__name__)
        self.current_task_id = None
        self._ensure_history_file()
        
    def _ensure_history_file(self):
        """确保历史文件存在"""
        if not os.path.exists(self.history_path):
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            self.logger.info(f"创建任务历史文件: {self.history_path}")
    
    def get_task_input(self) -> Tuple[str, bool]:
        """
        获取任务输入（简化版）
        
        流程：
        1. 等待用户输入
        2. 如果是普通任务文本：询问是否保存，然后返回任务
        3. 如果是'h'：显示历史任务，然后等待输入编号
        4. 如果是历史编号：调用历史任务，二次确认后返回
        
        Returns:
            Tuple[str, bool]: (任务内容, 是否为历史任务)
        """
        print("\n" + "="*60)
        print("请输入任务 (输入 'h' 查看历史任务，输入 'q' 退出):")
        print("="*60)
        
        while True:
            # 第一步：获取初始输入
            user_input = input("\n> ").strip()
            
            if not user_input:
                print("输入不能为空，请重新输入")
                continue
                
            if user_input.lower() == 'q':
                return None, False
                
            # 情况1：查询历史任务
            if user_input.lower() == 'h':
                task = self._handle_history_mode()
                if task:
                    return task, True
                # 如果没有选择历史任务，继续等待输入
                continue
                
            # 情况2：尝试解析为历史任务编号
            if user_input.isdigit():
                task = self._handle_task_id_input(user_input)
                if task:
                    return task, True
                # 如果不是有效的任务编号，继续等待输入
                continue
                
            # 情况3：普通任务文本
            # 询问是否保存
            should_save = self._ask_save_simple(user_input)
            if should_save:
                self.save_task(user_input)
            
            return user_input, False
    
    def _handle_history_mode(self) -> Optional[str]:
        """处理历史任务查询模式"""
        tasks = self.load_tasks()
        if not tasks:
            print("暂无历史任务")
            return None
        
        # 显示历史任务
        self._show_history_simple()
        
        # 等待用户输入编号
        print("\n请输入历史任务编号调用任务，或直接按回车返回:")
        while True:
            id_input = input("任务编号> ").strip()
            
            if not id_input:
                return None  # 直接回车返回
                
            if not id_input.isdigit():
                print("请输入有效的数字编号")
                continue
                
            task_id = int(id_input)
            task_record = self.get_task_by_id(task_id)
            
            if not task_record:
                print(f"任务 ID {task_id} 不存在")
                continue
                
            # 显示任务内容并确认
            task_content = task_record.get("task", "")
            print("\n" + "="*60)
            print(f"历史任务 {task_id}:")
            print("="*60)
            print(task_content)
            print("="*60)
            
            confirm = input("\n确认使用此任务？(y/n): ").strip().lower()
            if confirm in ['y', 'yes', '是']:
                self.current_task_id = task_id
                return task_content
            else:
                return None
    
    def _handle_task_id_input(self, input_str: str) -> Optional[str]:
        """处理任务编号输入"""
        task_id = int(input_str)
        task_record = self.get_task_by_id(task_id)
        
        if not task_record:
            # 不是有效的任务编号，可能用户想输入普通任务
            # 这里不返回，让上层继续处理
            return None
            
        # 显示任务内容并确认
        task_content = task_record.get("task", "")
        print("\n" + "="*60)
        print(f"检测到历史任务 {task_id}:")
        print("="*60)
        print(task_content)
        print("="*60)
        
        confirm = input("\n确认使用此历史任务？(y/n): ").strip().lower()
        if confirm in ['y', 'yes', '是']:
            self.current_task_id = task_id
            return task_content
            
        return None

    def _ask_save_simple(self, task: str) -> bool:
        """
        简化版保存询问
        
        规则：回车不保存，输入y再回车保存
        
        Args:
            task: 任务内容
            
        Returns:
            bool: 是否保存
        """
        print("\n" + "-"*40)
        print("是否保存此任务到历史记录？")
        print("规则: 直接按回车不保存，输入'y'再按回车保存")
        print("-"*40)
        
        choice = input("选择 (回车不保存，y保存): ").strip().lower()
        
        if choice == 'y':
            return True
        # 回车或其他输入都视为不保存
        return False

    def _show_history_simple(self):
        """简化版历史任务显示"""
        tasks = self.load_tasks()
        
        if not tasks:
            print("暂无历史任务")
            return
        
        print("\n" + "="*80)
        print(f"历史任务列表 (共{len(tasks)}个)")
        print("="*80)
        
        # 显示最近的任务
        recent_tasks = tasks[-20:]  # 显示最近20个
        
        for task_record in recent_tasks:
            task_id = task_record.get("id", "N/A")
            task_content = task_record.get("task", "")
            timestamp = task_record.get("timestamp", "")
            
            # 格式化时间
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    time_str = timestamp
            else:
                time_str = "未知时间"
            
            # 显示任务预览
            preview = task_content[:60] + "..." if len(task_content) > 60 else task_content
            
            print(f"[{task_id:3d}] [{time_str}] {preview}")
        
        print("="*80)
    
    def save_task(self, task: str, result: str = None, **kwargs) -> bool:
        """
        保存任务到历史记录
        
        Args:
            task: 任务内容
            **kwargs: 额外信息
            
        Returns:
            bool: 是否成功保存
        """
        try:
            # 修改点：加载整个键值对对象
            with open(self.history_path, 'r', encoding='utf-8') as f:
                history_obj = json.load(f)
            
            # 确定新ID：现有最大键值加1
            if history_obj:
                # 获取所有键，转换为整数，找出最大值
                max_id = max(int(key) for key in history_obj.keys())
                new_id = max_id + 1
            else:
                new_id = 1
            
            # 修改点：构建新的任务记录
            task_record = {
                "task": task,
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
            
            # 以字符串形式的ID为键，存储任务记录
            history_obj[str(new_id)] = task_record
            
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history_obj, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"任务已保存到历史记录，ID: {new_id}", 
                           extra={'tag': 'TASK_SAVED'})
            print(f"✓ 任务已保存，ID: {new_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"保存任务失败: {str(e)}", 
                            extra={'tag': 'TASK_SAVE_ERROR'})
            print(f"✗ 保存任务失败: {str(e)}")
            return False
    
    def load_tasks(self) -> List[Dict[str, Any]]:
        """加载所有任务历史，并转换为包含id字段的字典列表格式"""
        try:
            if not os.path.exists(self.history_path):
                return []
            
            with open(self.history_path, 'r', encoding='utf-8') as f:
                history_obj = json.load(f)
            
            tasks = []
            for task_id_str, task_data in history_obj.items():
                # 修改点：将键值对格式转换回包含id的字典
                try:
                    task_id = int(task_id_str)
                except ValueError:
                    # 如果键不是数字，跳过
                    continue
                    
                task_record = {
                    "id": task_id,
                    "task": task_data.get("task", ""),
                    "timestamp": task_data.get("timestamp", ""),
                }
                # 如果有其他在save_task时通过kwargs传入的字段，也一并保留
                for key, value in task_data.items():
                    if key not in ["task", "timestamp"]:
                        task_record[key] = value
                
                tasks.append(task_record)
            
            # 可选：按ID排序
            tasks.sort(key=lambda x: x["id"])
            return tasks
        except Exception as e:
            self.logger.error(f"加载任务历史失败: {str(e)}")
            return []
    
    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取任务"""
        try:
            if not os.path.exists(self.history_path):
                return None
            
            with open(self.history_path, 'r', encoding='utf-8') as f:
                history_obj = json.load(f)
            
            task_data = history_obj.get(str(task_id))
            if not task_data:
                return None
            
            # 修改点：将找到的数据包装成包含id的字典返回
            return {
                "id": task_id,
                "task": task_data.get("task", ""),
                "timestamp": task_data.get("timestamp", ""),
            }
        except Exception as e:
            self.logger.error(f"按ID获取任务失败: {str(e)}")
            return None
    
    def delete_task(self, task_id: int) -> bool:
        """删除任务"""
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                history_obj = json.load(f)
            
            if str(task_id) not in history_obj:
                self.logger.warning(f"要删除的任务 ID {task_id} 不存在")
                return False
            
            # 删除指定键
            del history_obj[str(task_id)]
            
            # 注意：在新格式下，删除后不重新编号，ID保持原有值不变
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history_obj, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"已删除任务 ID: {task_id}", extra={'tag': 'TASK_DELETED'})
            return True
            
        except Exception as e:
            self.logger.error(f"删除任务失败: {str(e)}")
            return False