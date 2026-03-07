# Claude Code SP 与工具定义分析

> 来源：`claude-code-reverse/results/` 逆向提取  
> 版本：Sonnet 4 (claude-sonnet-4-20250514)

---

## 1. SP 组成结构

Claude Code 的 system prompt 由以下部分拼接：

```
system-identity.prompt.md     → "You are Claude Code, Anthropic's official CLI for Claude."
system-workflow.prompt.md     → 主体 SP（角色、规则、工具策略）
[tools]                       → 15 个工具定义（Anthropic native tool calling）
system-reminder-start.prompt.md → <system-reminder> 开始（important-instruction-reminders）
[user messages]
system-reminder-end.prompt.md → <system-reminder> todo list 状态
```

## 2. Claude Code 的工具定义方式

**Claude Code 用的是 Anthropic 原生 tool calling**（不是 prompt injection）：
- 工具通过 `tools` 数组传入 Messages API
- 每个工具有 `name`, `description`, `input_schema`
- 模型输出 `tool_use` content block，客户端执行后返回 `tool_result`

**这与 thalamus 的场景完全不同：**
- thalamus 通过 Cursor API 转发，Cursor 不透传 Anthropic 的 `tools` 参数
- thalamus 必须用 prompt injection 模拟工具调用

## 3. 15 个工具清单

| 工具名 | 核心参数 | 说明 |
|--------|---------|------|
| **Bash** | command, timeout?, description? | 执行 shell 命令 |
| **Read** | file_path, offset?, limit? | 读文件（支持图片/PDF） |
| **Write** | file_path, content | 写文件 |
| **Edit** | file_path, old_string, new_string, replace_all? | 精确替换编辑 |
| **MultiEdit** | file_path, edits[] | 批量编辑 |
| **Glob** | pattern, path? | 文件名匹配 |
| **Grep** | pattern, path?, glob?, output_mode?, ... | ripgrep 搜索 |
| **Ls** | path, ignore? | 列目录 |
| **Task** | description, prompt, subagent_type | 启动子 agent |
| **TodoWrite** | todos[] | 任务管理 |
| **WebFetch** | url | 抓取网页 |
| **WebSearch** | query | 网络搜索 |
| **NotebookRead** | - | 读 Jupyter notebook |
| **NotebookEdit** | - | 编辑 Jupyter notebook |
| **ExitPlanMode** | - | 退出计划模式 |

## 4. 工具参数名对比（Claude Code vs thalamus 当前）

| Claude Code 参数名 | thalamus 当前 | 说明 |
|---|---|---|
| `file_path` | `path` / `file_path` 混用 | **需要统一** |
| `command` | `command` | 一致 |
| `content` | `contents` | **CC 用 content（无 s），thalamus 用 contents** |
| `old_string` | `old_string` | 一致 |
| `new_string` | `new_string` | 一致 |
| `pattern` | `pattern` | 一致 |
| `timeout` | 无 | CC 支持超时 |
| `description` (Bash) | 无 | CC 要求描述命令用途 |

## 5. SP 关键行为规则（与 thalamus 覆盖策略相关）

### 5.1 极简风格
```
You MUST answer concisely with fewer than 4 lines (not including tool use).
IMPORTANT: You should minimize output tokens as much as possible.
Do not add additional code explanation summary unless requested.
```
→ **thalamus 无需覆盖**，这是好的行为。

### 5.2 工具优先
```
VERY IMPORTANT: You MUST avoid using search commands like find and grep.
Instead use Grep, Glob, or Task to search.
You MUST avoid read tools like cat, head, tail, and ls, and use Read and LS.
```
→ **thalamus 需要在 prompt injection 中类似地强调用工具而非 bash 替代**。

### 5.3 自主执行
```
You are an agent - please keep going until the user's query is completely resolved.
Only terminate your turn when you are sure that the problem is solved.
```
→ **thalamus 的 "done!!" 机制与这个一致**。

### 5.4 任务管理
```
You have access to the TodoWrite tools. Use these tools VERY frequently.
```
→ **thalamus 当前不支持 TodoWrite，考虑是否需要。**

## 6. Cursor SP vs Claude Code SP 核心差异

| 维度 | Cursor SP | Claude Code SP |
|---|---|---|
| 工具传递 | `supported_tools` enum 列表 | Anthropic `tools` 数组 |
| 工具调用格式 | protobuf `ClientSideToolV2Call` | Anthropic `tool_use` content block |
| 系统提示位置 | server-side injection（不可控） | client-side（完全可控） |
| 代码修改指引 | "展示简化代码片段，建议切换 Agent" | "直接用 Edit/Write 工具执行" |
| 身份声明 | "AI coding assistant in Cursor" | "Claude Code, Anthropic's CLI" |
| 模式系统 | Agent/Plan/Debug/Ask | Agent/Plan (ExitPlanMode) |
