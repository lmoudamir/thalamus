# Thalamus-py 集成测试计划

## 测试方式
使用 `claude -p` CLI 通过 thalamus proxy 调用 Cursor API。

### CLI 必要参数
```bash
claude -p "<prompt>" \
  --model gpt-5.3-codex-spark-preview-xhigh \
  --max-turns <N> \
  --output-format text \
  --permission-mode bypassPermissions \
  --no-session-persistence \
  --debug 2>/dev/null &
echo "PID=$! at $(date +%T)"
```

### 已知问题
- CLI 间歇性挂住：根因是 auto-updater UI 在非 TTY 模式下阻塞。已在 settings.json 设置 `autoUpdaterStatus: "disabled"` 缓解。
- `normalize_content` 崩溃：已修复，处理嵌套 list 类型的 content。

---

## 测试等级

### Level 1: 纯文本回答 ✅ PASS
- **任务**: 简单数学/知识问题，不需工具调用
- **验证**: 回答正确，CLI 正常退出
- **结果**: `2+2=4`, `10+5=15`, `前5个质数=2,3,5,7,11` — 全部正确

### Level 2: 单文件读取 (Read) ✅ PASS
- **任务**: 读取 `test_puzzle/alpha.py` 并分析代码功能
- **验证**: 正确调用 Read 工具，正确解释代码
- **结果**: 成功调用 Read，正确分析 XOR 计算逻辑

### Level 3: 多文件读取 + 分析 ✅ PASS
- **任务**: 读取 3 个 puzzle 文件，分析每个的功能和输出
- **验证**: 连续调用 Read 3 次，分析全部正确
- **预期**: alpha.py→`Z=90|Y=89|X=88|W=87|V=86`, beta.js→`188`, gamma.sh→`result=55`
- **结果**: 3/3 全部正确。前 2 个文件直接 tool_use，第 3 个退化为文本模仿但被 mimicry interceptor 拦截转成真实 tool_use
- **关键修复**: 
  1. 历史 tool call 格式改为 `<tool_executed name="X" input={...} />`（保留参数做 few-shot，过去时态防模仿）
  2. tool_parser 新增 `_parse_text_mimicry()` 通用拦截器，捕获所有已知工具名+JSON参数的文本输出

### Level 4: Read + Write 工具链 ⚠️ PARTIAL
- **任务**: 读取 alpha.py 和 beta.js → 将分析写入 analysis.md
- **验证**: Read 和 Write 均被调用，文件内容正确
- **max-turns**: 8
- **结果**: 工具调用机制完美（8/8 全 tool_use，零文本模仿）。Read 正常，但 Write 的 content 参数被截断（第 1 次空，第 2 次仅标题）
- **根因**: Cursor model (gpt-5.3-codex-spark-preview-xhigh) 在 tool args 里生成长文本内容受限，非 thalamus 问题
- **关键验证**: tool_error/result 的 XML few-shot 格式有效，8 轮连续无退化

### Level 5: 完整 Agent 任务 (Read+Bash+Write) ✅ PASS
- **任务**: Read alpha.py/beta.js → Bash 执行 → Write results.md 对比报告
- **验证**: Read + Bash + Write 组合工作，报告内容正确
- **max-turns**: 12
- **结果**: 10/10 tool_use + 1 final text（零文本模仿）。完整跑通 Read→Bash(python3)→Bash(node)→Write。results.md 包含正确的对比表格，两个文件预测和实际输出完全一致。
- **关键修复**: 通用路径修正（文件系统反查，非硬编码映射）+ Bash 命令里 `!` 路径自动换单引号避 history expansion

### Level 6: 错误恢复 ✅ PASS
- **任务**: Read 不存在的文件 → 自动用 Glob 找到正确文件 → Read 并分析
- **验证**: tool_use_error 正确传回，LLM 自主切换到 Glob→Read 替代方案
- **max-turns**: 8
- **结果**: 3 tool_use (Read失败→Glob→Read) + 1 text，10秒完成。正确分析 alpha.py 并预测输出 `Z=90|Y=89|X=88|W=87|V=86`
- **关键发现**: `echo "" | claude -p` 管道 stdin 防止 CLI 挂住

### Level 7: 复杂多步推理 ✅ PASS
- **任务**: Glob(找 *.py 文件) → Read(tool_parser.py, offset=0 limit=40) → Write(生成 markdown 报告)
- **验证**: 三步工具链全部执行，报告内容正确
- **max-turns**: 12
- **结果**: 42 秒完成，报告包含 5 个文件列表 + tool_parser.py 准确功能摘要
- **关键修复**:
  1. URI 参数类型转换：`_coerce_param_types()` 将 query string 的 `offset`/`limit` 从 string 转 int，`true/false` 转 bool
  2. 此修复前，所有带 offset/limit 的 Read 调用都因类型错误无限循环
  3. `json.loads("null")` crash 防护：`isinstance(args, dict)` 检查
  4. heredoc 路径匹配：新增 `(?<=\n)` 正则模式

---

## 发现的问题与修复记录

| # | 问题 | 状态 | 修复 |
|---|------|------|------|
| 1 | `normalize_content` 崩溃: content 是嵌套 list | ✅ 已修 | pipeline.py: 递归处理非 str 的 raw |
| 2 | CLI 间歇挂住: auto-updater UI 阻塞 | 🔧 缓解 | settings.json: autoUpdaterStatus=disabled |
| 3 | thalamus 端点缺入参出参日志 | ✅ 已修 | 新增 thalamus_api_logger.py |
| 4 | 模型文本模拟 tool call 而非真正调用 | ✅ 已修 | tool_parser: `_parse_text_mimicry()` 通用拦截器，支持多种模仿格式 |
| 5 | `[Called Tool: X]` 格式被模型当模板模仿 | ✅ 已修 | tool_prompt_builder: 改用 `<tool_executed>` XML 自闭合标签，保留参数做 few-shot |
| 6 | tool result/error 缺少工具名，无法做 few-shot | ✅ 已修 | tool_prompt_builder: `<tool_result name="X">` / `<tool_error name="X">` 带工具名 |
| 7 | Write content 参数被截断（模型端限制） | ⚠️ 已知 | Cursor model 在 tool args 里生成长文本受限，非 thalamus 问题 |
| 8 | `!` 字符被模型生成为 `?`（路径混淆） | ✅ 已修 | pipeline: 通用文件系统反查修正（87/87 测试通过）+ Bash 里 `!` 路径自动换单引号 |
| 9 | URI 参数类型错误 (offset/limit 是 string 而非 int) | ✅ 已修 | `_coerce_param_types()` 自动转换数字/布尔类型 |
| 10 | `json.loads("null")` → None → `in None` crash | ✅ 已修 | `isinstance(args, dict)` 防护 |
| 11 | heredoc 换行后路径正则匹配不到 | ✅ 已修 | 新增 `(?<=\n)(/[^\s"']+)` 正则模式 |
| 12 | `claude -p` 无 stdin 管道时挂住 | 🔧 绕过 | 使用 `echo "" \| claude -p` 管道 stdin |
| 13 | Bash 命令中 `!` 被 Claude Code zsh eval 转义 | ⚠️ 已知 | Claude Code 内部 eval 机制导致 `!` → `\!`，非 thalamus 问题 |

---

## 上次测试时间
2026-03-03 19:01 (Level 6+7 通过 — 错误恢复 + Glob+Read(offset/limit)+Write 全链路)
