# TLM 集成测试方案

## 测试架构

```
claude -p (CC CLI) → tlm :3013 /v1/messages → Cursor API api2.cursor.sh
                         ↓ 日志                        ↓ 日志
              thalamus-api/payloads/         pipeline/payloads/
              req_*_request.json             cc_*_request.json
              req_*_response.json            cc_*_response.json
```

两层日志：
- **Layer 1 (thalamus-api)**：CC → tlm 的出入参（Anthropic 格式）
- **Layer 2 (pipeline)**：tlm → Cursor API 的出入参（protobuf 转文本后）

日志目录：`logs/<启动时间>/<日期>/thalamus-api/payloads/` 和 `logs/<启动时间>/<日期>/pipeline/payloads/`

## 测试用例

### Test 1：身份确认（无 tool calling）
- **模型**：`default`（最快）
- **输入**：`"你是谁？一句话"`
- **预期**：回复包含 "Claude Code" 或 "thalamus"，不包含 "Cursor"
- **验证点**：SP 双重注入生效，身份认同正确
- **超时**：15s

### Test 2：简单 tool calling — Write
- **模型**：`default`
- **输入**：`"用 Write tool 创建 /tmp/tlm-test/hello.txt 内容 Hello"`
- **预期**：模型输出 `{"tool_calls": [{"function": {"name": "Write", ...}}]}` JSON
- **验证点**：prompt injection 的 tool call 格式被模型正确遵循
- **超时**：15s

### Test 3：流式 thinking + text（composer-1.5）
- **模型**：`composer-1.5`
- **输入**：`"2+3=?"`
- **预期**：SSE 流中先出 `thinking: ` 前缀的 text_delta，再出正文
- **验证点**：thinking-as-text 功能、流式粒度
- **超时**：15s

### Test 4：前后端分离工程（完整 agent 能力）
- **模型**：`default`
- **max-turns**：5
- **输入**：`"在 /tmp/tlm-test 创建 app.py(FastAPI) 和 index.html，然后 ls 验证"`
- **预期**：多轮 tool calling（Write × 2 + Bash × 1）
- **验证点**：多轮对话、tool result 回传、连续执行
- **超时**：60s（多轮）

## 执行方式

所有测试用异步 Python 脚本跑（httpx.AsyncClient），直接调 `/v1/messages`，不依赖 `claude` CLI。

- 每个测试 fire-and-forget 发请求，用 `asyncio.wait_for` 控制超时
- 打印 SSE 事件流摘要（事件类型、text_delta 内容、tool_calls）
- 测试完后自动读取最新日志文件，打印两层出入参摘要

## 测试脚本

`/Users/ruicheng.gu/Documents/project/02-dev-tools/cursor-source-analysis/thalamus-py/tests/run_integration.py`

## 运行

```bash
cd /Users/ruicheng.gu/Documents/project/02-dev-tools/cursor-source-analysis/thalamus-py
python3 tests/run_integration.py
```
