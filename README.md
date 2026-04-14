# Agent Do Anything

基于 LangGraph 的本地 ReAct Agent 框架，支持多轮工具调用、会话持久化、上下文压缩与安全沙箱。

---

## 核心特性

### ReAct 执行循环
- 基于 LangGraph StateGraph 构建 `Think -> Act -> Observe -> Repeat` 的推理-行动循环
- 每个工具调用强制要求 `think` 参数，模型推理过程外化、可追踪
- 支持短任务模式（单轮执行）和长任务模式（拆分多个子任务，人机协作推进）

### 安全沙箱
- 策略分级：严格 / 标准 / 宽松三种模式，覆盖文件查看、Python 执行、Git 操作、高危命令等类别
- 交互式授权：未知或中等风险命令弹出终端确认 UI，不会静默执行
- 资源监控：通过 `psutil` 后台监控内存 / CPU，超限自动终止进程
- 危险模式拦截：正则匹配管道到 shell、`rm -rf /`、磁盘格式化等操作
- 目录白名单：限制命令只能在允许的路径范围内操作

### 上下文压缩与 Token 感知截断
- 为每条消息分配持久 `index`，支持模型按索引精准压缩或清理历史消息
- 自动检测并清除连续的空消息块
- 针对超大 Tool 返回结果，自动裁剪 `tool_calls` 参数以节省 Token，同时保留链式调用完整性
- 模型请求发送前进行 Token 估算，溢出时智能截断并自动重试（最多 3 次）

### 会话持久化与完整性修复
- 每次工具执行后自动保存会话状态到 SQLite，支持随时安全退出和断点续跑
- 恢复会话时自动扫描消息历史：
  - 尾部修复：自动补齐末尾悬空的 `ToolMessage` 或残缺的 `AIMessage.tool_calls`
  - 全量校验：发现历史中段损坏时，交互式询问是否修复；拒绝则标记为 `corrupted`，避免带病运行

### 内置工具集
- 文件操作（读、写、列目录、移动，带路径安全检查）
- 系统命令（通过沙箱执行终端命令）
- 网络请求（HTTP 请求、文件下载）
- 办公文档（PowerPoint / Word 读取与修改）
- 人机交互（`ask_user`、`submit_final_answer`、`submit_sub_task`）
- 上下文管理（按索引压缩/清空指定消息）

---

## 技术栈

Python · LangGraph · LangChain · Pydantic · SQLite · Click · PyInstaller

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/ThinkSeparate/agent-do-anything.git
cd agent-do-anything

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 LLM API Key 和模型配置

# 4. 运行
python main.py
```

---

## 架构概览

```
agent_do_anything/
├── core/
│   ├── react/
│   │   ├── agent.py          # ReActAgent 主类，短/长任务调度入口
│   │   ├── build_agent.py    # LangGraph 状态图构建
│   │   ├── agent_logic.py    # 节点路由：should_continue
│   │   └── prompts.py        # 系统提示模板
│   ├── common/
│   │   ├── model_node.py     # LLM 调用节点（重试、Token 截断、Usage 日志）
│   │   ├── tool_node.py      # 工具执行节点（消息压缩、状态持久化）
│   │   ├── message_validator.py  # 消息完整性校验与修复
│   │   └── agent_utils.py    # 配置加载、模型初始化、Prompt 渲染
│   └── sandbox/
│       ├── executor.py       # 沙箱执行器
│       └── config_ui.py      # 沙箱策略交互配置终端
├── tools/
│   ├── file_tools.py
│   ├── system_tools.py
│   ├── network_tools.py
│   ├── office_tools.py
│   ├── interactive_tools.py
│   ├── compress_messages.py
│   └── wrap_with_think.py    # 为所有工具注入强制 think 参数
├── utils/
│   ├── session_persistence.py    # SQLite 会话持久化
│   ├── message_processor.py      # 消息预处理（压缩、截断、清理）
│   ├── token_utils.py            # Token 估算
│   └── task_manager.py           # CLI 任务历史浏览器
└── config/
    ├── configuration.py
    └── sandbox_policy.yaml
```

---

## License

个人独立作品，仅供学习与技术交流使用。未经许可不得用于商业目的。
