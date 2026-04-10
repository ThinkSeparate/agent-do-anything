"""沙盒配置交互式界面 - 让用户轻松配置安全策略"""

import os
from typing import Optional

import yaml


class SandboxConfigUI:
    """
    沙盒配置交互式界面

    提供友好的命令行界面，让用户无需编辑YAML即可配置沙盒策略
    使用 UserProfile 统一存储用户配置
    """

    def __init__(self, project_directory: str):
        self.project_directory = project_directory
        self.default_config_file = os.path.join(
            project_directory, "config", "sandbox_policy.yaml"
        )

        # 加载默认配置
        self.default_policy = self._load_default_policy()

        # 从 UserProfile 加载用户配置
        from utils.user_profile import get_user_profile
        self.user_profile = get_user_profile(project_directory)
        self.policy = self._build_policy()

    def _load_default_policy(self) -> dict:
        """加载默认配置"""
        try:
            with open(self.default_config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {"mode": "normal"}
        except Exception:
            return {"mode": "normal"}

    def _build_policy(self) -> dict:
        """合并默认配置和用户配置"""
        policy = self.default_policy.copy()

        # 从 UserProfile 获取用户配置
        sandbox_policy = self.user_profile.sandbox_policy
        if sandbox_policy.get('mode'):
            policy['mode'] = sandbox_policy['mode']
        if sandbox_policy.get('custom_rules'):
            policy['custom_rules'] = sandbox_policy['custom_rules']

        return policy

    def _save_policy(self):
        """保存用户配置到 UserProfile"""
        try:
            # 保存模式
            if self.policy.get("mode") != self.default_policy.get("mode", "normal"):
                self.user_profile.sandbox_mode = self.policy["mode"]

            # 保存自定义规则
            if "custom_rules" in self.policy:
                # 清除旧规则并设置新规则
                self.user_profile.clear_sandbox_custom_rules()
                for cat_key, cat_rules in self.policy["custom_rules"].items():
                    for cmd, rule in cat_rules.items():
                        self.user_profile.set_sandbox_custom_rule(cat_key, cmd, rule)

            return True
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
            return False

    def show_welcome(self):
        """显示欢迎信息"""
        print("\n" + "=" * 70)
        print("🔒 沙盒安全配置向导")
        print("=" * 70)
        print(
            "\n沙盒系统控制 Agent 执行命令时的安全策略："
            "\n  • 哪些命令可以自动执行"
            "\n  • 哪些命令需要确认"
            "\n  • 超时和资源限制"
        )
        print("\n" + "-" * 70)

    def show_current_status(self):
        """显示当前配置状态"""
        mode = self.policy.get("mode", "normal")
        mode_desc = {
            "strict": "严格模式 - 所有命令都需要确认",
            "normal": "标准模式 - 危险命令需要确认",
            "permissive": "宽松模式 - 只有高危命令需要确认",
        }

        print("\n📋 当前配置:")
        print(f"   模式: {mode_desc.get(mode, mode)}")

        # 从 command_categories 计算允许的命令数量
        categories = self.policy.get("command_categories", {})
        total_cmds = 0
        for cat_config in categories.values():
            total_cmds += len(cat_config.get("strict", []))
            total_cmds += len(cat_config.get("normal", []))
            total_cmds += len(cat_config.get("permissive", []))
        print(f"   允许命令: {total_cmds} 条")

        # 显示目录限制
        allowed_dirs = self.policy.get("allowed_directories", [])
        if allowed_dirs:
            print(f"   允许目录: {len(allowed_dirs)} 个")

    def select_mode(self) -> Optional[str]:
        """交互式选择模式"""
        print("\n📌 请选择沙盒模式:\n")

        modes = [
            ("strict", "严格模式", "所有命令都需要确认，最安全"),
            ("normal", "标准模式 ⭐推荐", "常用命令自动执行，危险命令需确认"),
            ("permissive", "宽松模式", "只有高危命令需要确认"),
            ("unattended", "无人值守模式", "完全依赖白名单，适合长期运行"),
        ]

        for i, (key, name, desc) in enumerate(modes, 1):
            marker = "✓" if self.policy.get("mode") == key else " "
            print(f"   [{marker}] {i}. {name}")
            print(f"       {desc}\n")

        print("   [ ] 0. 保持当前设置")
        print("\n" + "-" * 70)

        while True:
            choice = input("请选择 (0-4): ").strip()
            if choice == "0":
                return None  # 保持当前
            if choice in ["1", "2", "3", "4"]:
                return modes[int(choice) - 1][0]
            print("❌ 无效选择，请重试")

    def manage_whitelist(self):
        """管理白名单"""
        whitelist = self.policy.get("unattended_whitelist", [])

        while True:
            print("\n" + "=" * 70)
            print("📋 白名单管理（无人值守模式下自动执行的命令）")
            print("=" * 70)

            if whitelist:
                print(f"\n当前白名单 ({len(whitelist)} 条):")
                for i, cmd in enumerate(whitelist[:20], 1):
                    print(f"  {i:2d}. {cmd}")
                if len(whitelist) > 20:
                    print(f"  ... 还有 {len(whitelist) - 20} 条")
            else:
                print("\n当前白名单为空")

            print("\n操作:")
            print("  [1] 添加常用命令模板")
            print("  [2] 手动输入命令")
            print("  [3] 删除命令")
            print("  [4] 清空白名单")
            print("  [0] 返回")

            choice = input("\n请选择: ").strip()

            if choice == "1":
                self._add_template_commands()
            elif choice == "2":
                self._add_manual_command()
            elif choice == "3":
                self._remove_command()
            elif choice == "4":
                if input("确认清空白名单？(y/n): ").lower() == "y":
                    whitelist.clear()
                    print("✓ 白名单已清空")
            elif choice == "0":
                break

            self.policy["unattended_whitelist"] = whitelist
            self._save_policy()

    def _add_template_commands(self):
        """添加模板命令"""
        # 从YAML读取命令分类作为模板
        templates = {}
        categories = self.policy.get("command_categories", {})
        for cat_key, cat_config in categories.items():
            cat_name = cat_config.get("name", cat_key)
            # 合并所有模式的命令，并添加通配符
            all_cmds = (
                cat_config.get("strict", []) +
                cat_config.get("normal", []) +
                cat_config.get("permissive", [])
            )
            # 添加通配符版本
            templates[cat_name] = [cmd + " *" if " " not in cmd else cmd + " *" for cmd in all_cmds[:10]]

        print("\n可选模板:")
        for i, (name, _) in enumerate(templates.items(), 1):
            print(f"  [{i}] {name}")
        print("  [0] 返回")

        choice = input("\n请选择: ").strip()
        if choice == "0":
            return

        try:
            idx = int(choice) - 1
            category = list(templates.keys())[idx]
            commands = templates[category]

            print(f"\n将添加以下命令 ({category}):")
            for cmd in commands:
                print(f"  - {cmd}")

            if input("确认添加？(y/n): ").lower() == "y":
                whitelist = self.policy.get("unattended_whitelist", [])
                added = 0
                for cmd in commands:
                    if cmd not in whitelist:
                        whitelist.append(cmd)
                        added += 1
                print(f"✓ 已添加 {added} 条命令")
        except (ValueError, IndexError):
            print("❌ 无效选择")

    def _add_manual_command(self):
        """手动添加命令"""
        print("\n提示:")
        print("  • 使用 * 作为通配符，如 'python *' 匹配任何python命令")
        print("  • 精确命令如 'git status' 只匹配该命令")
        print("  • 建议先测试命令是否安全")

        cmd = input("\n请输入命令模式: ").strip()
        if cmd:
            whitelist = self.policy.get("unattended_whitelist", [])
            if cmd in whitelist:
                print("⚠️ 该命令已存在")
            else:
                whitelist.append(cmd)
                print(f"✓ 已添加: {cmd}")

    def _remove_command(self):
        """删除命令"""
        whitelist = self.policy.get("unattended_whitelist", [])
        if not whitelist:
            print("白名单为空")
            return

        cmd_id = input("请输入要删除的命令编号: ").strip()
        try:
            idx = int(cmd_id) - 1
            if 0 <= idx < len(whitelist):
                removed = whitelist.pop(idx)
                print(f"✓ 已删除: {removed}")
            else:
                print("❌ 编号超出范围")
        except ValueError:
            print("❌ 无效输入")

    def run_setup(self) -> bool:
        """
        运行配置向导

        Returns:
            True 如果配置有变更
        """
        while True:
            self.show_sandbox_menu()

            choice = input("> ").strip().lower()

            if choice == 'q':
                return False

            if choice == '0':
                # 查看详细配置
                result = self.show_detailed_config()
                if result == 'main_menu':
                    return True  # 返回主菜单
                continue

            if choice in ['1', '2', '3']:
                mode_map = {
                    '1': ('strict', '严格模式'),
                    '2': ('normal', '标准模式'),
                    '3': ('permissive', '宽松模式')
                }
                new_mode, mode_name = mode_map[choice]
                current_mode = self.policy.get('mode', 'normal')

                if new_mode == current_mode:
                    print(f"\nℹ️ 已经是{mode_name}了")
                    input("\n按回车继续...")
                    continue

                # 二次确认
                has_custom = bool(self.policy.get("custom_rules"))
                print(f"\n是否切换到 {mode_name}？(Y/N)")
                if has_custom:
                    print("⚠️  注意：当前存在用户定制策略，切换模式后仍优先使用定制规则")
                confirm = input("> ").strip().upper()
                if confirm == 'Y':
                    self.policy['mode'] = new_mode
                    if self._save_policy():
                        print(f"\n✅ 已切换到 {mode_name}")
                    else:
                        print("\n❌ 配置保存失败")
                    input("\n按回车继续...")
                continue

            print("\n❌ 无效选择，请重试")

    def show_sandbox_menu(self):
        """显示沙盒配置菜单"""
        current_mode = self.policy.get('mode', 'normal')

        # 获取白名单和允许目录数量
        whitelist = self.policy.get("unattended_whitelist", [])
        whitelist_count = len(whitelist)
        allowed_dirs = self.policy.get("allowed_directories", [])
        dirs_count = len(allowed_dirs)

        # 当前模式描述（只有3种基础模式）
        mode_desc_map = {
            'strict': '严格模式 - 所有命令都需要确认',
            'normal': '标准模式 - 常用命令自动执行，危险命令需确认',
            'permissive': '宽松模式 - 只有高危命令需要确认'
        }

        print("\n" + "=" * 60)
        print("🔒 沙盒安全配置")
        print("=" * 60)
        print("当前配置摘要:")
        print(f"  模式: {mode_desc_map.get(current_mode, current_mode)}")
        print(f"  命令白名单: {whitelist_count}条")
        print(f"  允许路径: {dirs_count}个")
        print("-" * 60)

        # 模式选项，只在当前模式前显示 [✓]
        modes = [
            ('strict', '1', '严格模式', '所有命令都需要确认'),
            ('normal', '2', '标准模式 ⭐', '常用命令自动执行，危险命令需确认'),
            ('permissive', '3', '宽松模式', '只有高危命令需要确认'),
        ]

        for mode_key, num, name, desc in modes:
            marker = '[✓] ' if current_mode == mode_key else ''
            print(f"[{num}] {marker}{name:<12} - {desc}")

        print()
        print("[0] 查看详细配置")
        print("[q] 返回")
        print("-" * 60)

    def _display_width(self, text: str) -> int:
        """计算字符串在终端中的显示宽度（CJK中文占2，其他占1）"""
        width = 0
        for char in text:
            code = ord(char)
            # CJK统一汉字: 0x4e00-0x9fff
            if 0x4e00 <= code <= 0x9fff:
                width += 2
            # 全角字符范围 (FF01-FF60)
            elif 0xff01 <= code <= 0xff60:
                width += 2
            # 其他字符(包括✓✗○等Unicode符号)都是半角
            else:
                width += 1
        return width

    def _pad(self, text: str, target_width: int) -> str:
        """用空格填充到目标显示宽度"""
        current_width = self._display_width(text)
        padding = target_width - current_width
        return text + ' ' * max(0, padding)

    def show_detailed_config(self):
        """显示详细配置对比表"""
        while True:
            # 列宽定义（显示宽度）- 中文占2宽
            idx_width = 4   # [N] = 4宽
            cat_width = 12  # 类别名（4-6中文=8-12宽）
            mode_width = 8  # 模式列
            custom_width = 6  # 定制列
            total_width = 52  # 4列模式

            # 从YAML读取命令分类
            categories = self.policy.get("command_categories", {})

            # 检查哪些类别有用户定制
            custom_rules = self.policy.get("custom_rules", {})

            print("\n" + "=" * total_width)
            mode_display = {
                'strict': '严格模式',
                'normal': '标准模式',
                'permissive': '宽松模式'
            }.get(self.policy.get('mode', 'normal'), '标准模式')
            print(f"📊 命令执行策略对比表 (当前模式: {mode_display})")
            print("=" * total_width)

            # 表头：3种基础模式 + 定制列
            header_idx = self._pad("", idx_width)
            header_cat = self._pad("命令类别", cat_width)
            header_strict = self._pad("严格模式", mode_width)
            header_normal = self._pad("标准模式", mode_width)
            header_permissive = self._pad("宽松模式", mode_width)
            header_custom = self._pad("定制", custom_width)
            print(f"{header_idx} {header_cat} {header_strict} {header_normal} {header_permissive} {header_custom}")
            print("-" * total_width)

            for i, (cat_key, cat_config) in enumerate(categories.items(), 1):
                cat_name = cat_config.get('name', cat_key)
                has_custom = "✓" if cat_key in custom_rules else ""
                idx = self._pad(f"[{i}]", idx_width)
                cat = self._pad(cat_name, cat_width)
                # 计算每个模式 + 用户定制的实际结果
                strict_status = self._get_category_status_for_mode(cat_key, cat_config, "strict")
                normal_status = self._get_category_status_for_mode(cat_key, cat_config, "normal")
                permissive_status = self._get_category_status_for_mode(cat_key, cat_config, "permissive")
                strict = self._pad(strict_status, mode_width)
                normal = self._pad(normal_status, mode_width)
                permissive = self._pad(permissive_status, mode_width)
                custom = self._pad(has_custom, custom_width)
                print(f"{idx} {cat} {strict} {normal} {permissive} {custom}")

            print("-" * total_width)
            print("图例: ✓=全部允许  ○=部分允许  ✗=全部禁止")
            print("      定制✓=存在用户自定义规则")
            print("-" * total_width)
            print("[1-7] 查看及定制  [8] 路径限制  [9] 资源限制  [0] 返回  [q] 主菜单")
            print("=" * total_width)

            choice = input("> ").strip().lower()

            if choice == 'q':
                return 'main_menu'
            elif choice == '0':
                return None
            elif choice == '8':
                self._show_path_limits()
            elif choice == '9':
                self._show_resource_limits()
            elif choice.isdigit() and 1 <= int(choice) <= len(categories):
                idx = int(choice) - 1
                cat_key = list(categories.keys())[idx]
                self._show_category_detail(cat_key, categories[cat_key])
            else:
                print("❌ 无效选择")

    def _get_mode_symbols(self, cat_type: str) -> dict:
        """获取各模式下的符号表示

        三种状态：
        - ✓ = 全部允许（自动执行）
        - ✗ = 全部禁止
        - ○ = 部分允许（需确认或依赖白名单）
        """
        symbols = {
            # strict: 所有类别都需确认
            "readonly": {"strict": "✗", "normal": "✓", "permissive": "✓"},
            "write": {"strict": "✗", "normal": "✗", "permissive": "✓"},
            "network": {"strict": "✗", "normal": "✗", "permissive": "✗"},
            "dangerous": {"strict": "✗", "normal": "✗", "permissive": "✗"},
        }
        return symbols.get(cat_type, {"strict": "?", "normal": "?", "permissive": "?"})

    def _get_category_status_for_mode(self, cat_key: str, cat_config: dict, mode: str) -> str:
        """根据YAML配置和用户定制计算类别在指定模式下的实际状态

        Args:
            cat_key: 类别键名（英文）
            cat_config: 类别配置（包含strict/normal/permissive/forbidden）
            mode: 模式（strict/normal/permissive）

        Returns:
            "✓" - 全部允许（所有命令都可执行）
            "✗" - 全部禁止（所有命令都不可执行）
            "○" - 部分允许（部分命令可执行）
        """
        # 获取所有唯一命令（四类加总）
        all_cmds = set()
        all_cmds.update(cat_config.get("strict", []))
        all_cmds.update(cat_config.get("normal", []))
        all_cmds.update(cat_config.get("permissive", []))
        all_cmds.update(cat_config.get("forbidden", []))
        total = len(all_cmds)

        if total == 0:
            return "✗"

        # 计算基础模式允许数
        strict_cmds = set(cat_config.get("strict", []))
        normal_cmds = strict_cmds | set(cat_config.get("normal", []))
        permissive_cmds = normal_cmds | set(cat_config.get("permissive", []))
        forbidden = set(cat_config.get("forbidden", []))

        if mode == "strict":
            base_allowed = strict_cmds - forbidden
        elif mode == "normal":
            base_allowed = normal_cmds - forbidden
        else:  # permissive
            base_allowed = permissive_cmds - forbidden

        # 加上用户定制调整
        custom_rules = self.policy.get("custom_rules", {})
        cat_custom = custom_rules.get(cat_key, {})

        # 用户允许的命令（不在基础允许中的）
        for cmd, rule in cat_custom.items():
            if rule == "allow" and cmd not in base_allowed:
                base_allowed.add(cmd)
            elif rule == "deny" and cmd in base_allowed:
                base_allowed.discard(cmd)

        final_allowed = len(base_allowed)

        if final_allowed == total:
            return "✓"
        elif final_allowed == 0:
            return "✗"
        else:
            return "○"

    def _get_category_actual_status(self, cat_name: str, cat_type: str, commands: list, base_mode: str) -> str:
        """计算类别在当前模式下的实际状态

        Returns:
            "✓" - 全部允许（自动执行）
            "✗" - 全部禁止（或全部需确认）
            "○" - 部分允许（混合状态）
        """
        custom_rules = self.policy.get("custom_rules", {})
        cat_custom = custom_rules.get(cat_name, {})

        # 获取基础模式的符号规则
        base_symbols = self._get_mode_symbols(cat_type)
        base_symbol = base_symbols.get(base_mode, "○")

        allow_count = 0
        deny_count = 0

        for cmd in commands:
            # 检查用户自定义
            user_rule = cat_custom.get(cmd)
            if user_rule == "allow":
                allow_count += 1
            elif user_rule == "deny":
                deny_count += 1
            else:
                # 跟随基础模式
                if base_symbol == "✓":
                    allow_count += 1
                else:
                    deny_count += 1

        total = len(commands)
        if allow_count == total:
            return "✓"  # 全部允许
        elif deny_count == total:
            return "✗"  # 全部禁止
        else:
            return "○"  # 部分允许

    def _get_command_status(self, cmd: str, cat_key: str, cat_config: dict, base_mode: str) -> str:
        """获取命令当前状态"""
        # 检查用户自定义
        custom_rules = self.policy.get("custom_rules", {})
        cat_rules = custom_rules.get(cat_key, {})
        user_rule = cat_rules.get(cmd)

        if user_rule == "allow":
            return "[用户允许]"
        if user_rule == "deny":
            return "[用户禁止]"

        # 根据基础模式和 YAML 配置判断
        strict_cmds = set(cat_config.get("strict", []))
        normal_cmds = strict_cmds | set(cat_config.get("normal", []))
        permissive_cmds = normal_cmds | set(cat_config.get("permissive", []))
        forbidden = set(cat_config.get("forbidden", []))

        if cmd in forbidden:
            return "[禁止]"

        if base_mode == "strict":
            allowed = strict_cmds
        elif base_mode == "normal":
            allowed = normal_cmds
        else:
            allowed = permissive_cmds

        if cmd in allowed:
            return "[允许]"
        else:
            return "[禁止]"

    def _show_category_detail(self, category_key: str, category_config: dict):
        """显示类别详情及定制界面"""
        cat_key = category_key
        cat_name = category_config.get('name', category_key)
        cat_config = category_config

        # 合并所有命令
        commands = (
            cat_config.get("strict", []) +
            cat_config.get("normal", []) +
            cat_config.get("permissive", []) +
            cat_config.get("forbidden", [])
        )
        # 去重但保持顺序
        seen = set()
        unique_commands = []
        for cmd in commands:
            if cmd and cmd not in seen:
                seen.add(cmd)
                unique_commands.append(cmd)
        commands = unique_commands

        base_mode = self.policy.get("mode", "normal")

        while True:
            print(f"\n{'=' * 60}")
            print(f"📁 {cat_name} ({cat_key}) - 查看及定制")
            print(f"{'=' * 60}")
            print(f"当前模式: {base_mode}")
            print()

            # 显示命令列表及状态
            for i, cmd in enumerate(commands, 1):
                status = self._get_command_status(cmd, cat_key, cat_config, base_mode)
                print(f"{i:2d}. {cmd:<20} {status}")

            print(f"\n{'-' * 60}")
            print("> allow/deny all                 全部允许/禁止")
            print("> allow/deny <序号1>,<序号2>...  按序号允许/禁止")
            print("> clear                          清除自定义")
            print("> q                              返回")
            print(f"{'-' * 60}")

            user_input = input("> ").strip()

            if user_input.lower() == "q":
                return
            elif user_input.lower() == "clear":
                self._clear_category_rules(cat_key)
                print(f"✅ 已清除 {cat_name} 的自定义设置")
            elif user_input.lower() in ("allow all", "deny all"):
                action = user_input.split()[0].lower()
                self._set_category_all(cat_key, commands, action)
                print(f"✅ 已设置 {cat_name} 全部{('允许' if action == 'allow' else '禁止')}")
            elif user_input.lower().startswith(("allow ", "deny ")):
                parts = user_input.split(maxsplit=1)
                if len(parts) == 2:
                    action, indices_str = parts
                    action = action.lower()
                    try:
                        indices = [int(x.strip()) for x in indices_str.split(",")]
                        valid_indices = [i for i in indices if 1 <= i <= len(commands)]
                        if valid_indices:
                            self._set_commands_rules(cat_key, commands, valid_indices, action)
                            print(f"✅ 已设置指定命令{('允许' if action == 'allow' else '禁止')}")
                        else:
                            print("❌ 无效序号")
                    except ValueError:
                        print("❌ 格式错误，示例: allow 1,2,3")
                else:
                    print("❌ 格式错误")
            else:
                print("❌ 无效命令")

    def _clear_category_rules(self, cat_name: str):
        """清除类别自定义规则"""
        if "custom_rules" in self.policy and cat_name in self.policy["custom_rules"]:
            del self.policy["custom_rules"][cat_name]
            self._save_policy()

    def _set_category_all(self, cat_name: str, commands: list, action: str):
        """设置整个类别的规则"""
        if "custom_rules" not in self.policy:
            self.policy["custom_rules"] = {}
        if cat_name not in self.policy["custom_rules"]:
            self.policy["custom_rules"][cat_name] = {}

        for cmd in commands:
            self.policy["custom_rules"][cat_name][cmd] = action
        self._save_policy()

    def _set_commands_rules(self, cat_name: str, commands: list, indices: list, action: str):
        """设置指定命令的规则"""
        if "custom_rules" not in self.policy:
            self.policy["custom_rules"] = {}
        if cat_name not in self.policy["custom_rules"]:
            self.policy["custom_rules"][cat_name] = {}

        for idx in indices:
            cmd = commands[idx - 1]
            self.policy["custom_rules"][cat_name][cmd] = action
        self._save_policy()

    def _show_path_limits(self):
        """显示路径限制"""
        allowed = self.policy.get("allowed_directories", [])
        forbidden = self.policy.get("forbidden_directories", [])

        print(f"\n{'=' * 60}")
        print("📂 路径限制配置")
        print(f"{'=' * 60}")

        print(f"\n✅ 允许访问的目录 ({len(allowed)} 个):")
        if allowed:
            for d in allowed:
                print(f"  • {d}")
        else:
            print("  (未配置，默认仅允许项目目录)")

        print(f"\n❌ 禁止访问的目录 ({len(forbidden)} 个):")
        if forbidden:
            for d in forbidden:
                print(f"  • {d}")
        else:
            print("  (未配置)")

        print(f"\n{'-' * 60}")
        input("按回车继续...")

    def _show_resource_limits(self):
        """显示资源限制"""
        timeouts = self.policy.get("timeouts", {})
        resources = self.policy.get("resource_limits", {})

        print(f"\n{'=' * 60}")
        print("⚡ 资源限制配置")
        print(f"{'=' * 60}")

        print(f"\n⏱️  超时设置 (秒):")
        print(f"  默认超时: {timeouts.get('default', 30)}s")
        print(f"  长任务超时: {timeouts.get('long_running', 300)}s")
        print(f"  网络超时: {timeouts.get('network', 60)}s")

        print(f"\n💾 资源限制:")
        print(f"  最大内存: {resources.get('max_memory_mb', '未设置')} MB")
        print(f"  CPU限制: {resources.get('max_cpu_percent', '未设置')}%")
        print(f"  磁盘读取: {resources.get('max_disk_read_mb', '未设置')} MB/s")
        print(f"  磁盘写入: {resources.get('max_disk_write_mb', '未设置')} MB/s")

        print(f"\n{'-' * 60}")
        input("按回车继续...")


def quick_setup_sandbox(project_directory: str) -> bool:
    """
    快速设置沙盒（供agent.py调用）

    Returns:
        True 如果用户修改了配置
    """
    ui = SandboxConfigUI(project_directory)
    return ui.run_setup()


def show_sandbox_status(project_directory: str):
    """显示沙盒状态（启动时显示）"""
    ui = SandboxConfigUI(project_directory)
    ui.show_current_status()
