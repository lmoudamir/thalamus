<p align="center">
  <img src="assets/logo.png" alt="Thalamus Logo" />
</p>

<h1 align="center">Thalamus</h1>

<p align="center">
  <em>"Not the mind. The gateway to it."</em>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#key-features">Features</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#configuration">Config</a> •
  <a href="#desktop-app">Desktop App</a> •
  <a href="#中文说明">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" />
  <img src="https://img.shields.io/badge/API-Anthropic%20%2B%20OpenAI-orange" alt="Dual API" />
</p>

---

**Use your [Cursor](https://cursor.com) subscription to power [Claude Code](https://docs.anthropic.com/en/docs/claude-code).** No separate Anthropic API key needed — Thalamus bridges the gap so Claude Code runs seamlessly on Cursor's models.

### Why does this exist?

- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** is Anthropic's terminal-based AI coding agent — it edits files, runs commands, and manages projects autonomously. But it requires a paid Anthropic API key.
- **[Cursor](https://cursor.com)** is an AI-powered IDE with its own subscription that includes access to powerful models (Claude, GPT, etc.) — but only inside Cursor's editor.
- **Thalamus** connects the two: it runs on your machine, pretends to be Anthropic's API, and forwards everything to Cursor's backend. Claude Code thinks it's talking to Anthropic, but it's actually using your existing Cursor subscription.

**Result:** You get Claude Code's full autonomous coding power, paid for by the Cursor subscription you already have.

```
Claude Code                                                    Cursor API
    │                                                              ▲
    │  POST /v1/messages                                           │
    │  (Anthropic format)                                          │
    ▼                                                              │
┌──────────────────────────────────────────────────────────────────┐
│                        T H A L A M U S                           │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  Protocol    │  │  Tool Call   │  │  Model Fallback         │ │
│  │  Translation │→ │  Enhancement │→ │  & Auto-Continuation    │ │
│  │              │  │  (LTLP)      │  │                         │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
│                                                                  │
│  Anthropic ↔ Protobuf  │  Lazy stubs → full schema  │  Retry    │
└──────────────────────────────────────────────────────────────────┘
```

## Key Features

### 🔮 Lazy Tool Loading Protocol (LTLP)

**Problem:** Claude Code registers 40+ tools (file read, file write, bash, search, etc.) — that's ~27,000 tokens of tool definitions sent with every request. Cursor's API doesn't natively support tool definitions, so other proxies either skip tools entirely or bloat every prompt.

**Solution:** Thalamus compresses all tool definitions into ultra-compact one-line stubs (~1KB total). When the model tries to use a tool, Thalamus teaches it the correct parameters on-the-fly:

```
Turn 1:  Model sees stub "Write – create/overwrite files" → tries to call with guessed args
Turn 2:  Thalamus intercepts, returns full schema as context → model learns the correct format
Turn 3:  Model calls correctly — and remembers for all subsequent calls
```

### 🔄 Auto-Continuation with `task_complete`

**Problem:** Cursor's API doesn't tell us *why* the model stopped responding (did it finish? is it thinking? did it get confused?). Other proxies just assume "done" — causing Claude Code to stop mid-task, often after just describing what it *would* do without actually doing it.

**Solution:** Thalamus adds a `task_complete` signal. If the model outputs text but doesn't call any tool and doesn't explicitly say "I'm done," Thalamus nudges it: "You described the plan, now execute it." The text and subsequent tool calls get merged into one seamless response. Claude Code never sees the retry.

### 🛡️ Smart Model Fallback

**Problem:** Sometimes a model is overloaded, rate-limited, or just slow. Your coding session shouldn't stall because of it.

**Solution:** If the first response token doesn't arrive within a configurable timeout (default 10s), Thalamus automatically retries with the next model in a priority chain. No manual switching needed.

### 📡 Dual API Compatibility

Thalamus serves both Anthropic (`/v1/messages`) and OpenAI (`/v1/chat/completions`) formats from the same backend. This means you can use it with:
- **Claude Code** (Anthropic format)
- **aider, Open WebUI, LangChain** (OpenAI format)
- Any custom script using the `openai` or `anthropic` Python SDK

## Quick Start (5 minutes)

### Prerequisites

| Requirement | Why | How to check |
|---|---|---|
| **Python 3.10+** | Thalamus is a Python server | `python3 --version` |
| **Cursor Pro/Business** | Provides the model access you'll use | You're logged into [cursor.com](https://cursor.com) |
| **Claude Code CLI** | The agent that Thalamus powers | `claude --version` (install: `npm install -g @anthropic-ai/claude-code`) |
| **Node.js 18+** | Required by Claude Code CLI | `node --version` |

### Step 1: Install

```bash
git clone https://github.com/guojun21/thalamus.git
cd thalamus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Get Your Cursor Token

Thalamus needs your Cursor authentication token to make API calls on your behalf. Choose one method:

**Option A: Browser Login (easiest)**

```bash
python server.py                              # Start the server first
# Open http://localhost:3013/cursor/login in your browser
# Log in with your Cursor account — token is saved automatically
```

**Option B: Extract from Cursor IDE**

1. Open Cursor IDE
2. Open DevTools: `Cmd+Shift+I` (Mac) / `Ctrl+Shift+I` (Windows/Linux)
3. Go to the **Network** tab
4. Type anything in the chat to trigger a request
5. Click any request to `api2.cursor.sh`
6. Find the `Authorization` header — copy the full value (starts with `user_`)
7. Create your config:

```bash
cp .env.example .env
# Edit .env and paste your token:
# CURSOR_TOKEN=user_xxxxx::eyJhbGciOi...
```

> **How long does a token last?** Typically ~60 days. When it expires, you'll see authentication errors — just repeat this step to get a fresh one.

### Step 3: Start Thalamus

```bash
python server.py
```

Expected output:

```
INFO:     Uvicorn running on http://0.0.0.0:3013
```

Verify it's working:

```bash
curl http://localhost:3013/health
# Expected: {"status":"ok","has_token":true}
#
# If you see "has_token":false, your token isn't configured — go back to Step 2
```

### Step 4: Connect Claude Code

Tell Claude Code to talk to Thalamus instead of Anthropic's servers:

```bash
export ANTHROPIC_BASE_URL=http://localhost:3013
export ANTHROPIC_API_KEY=thalamus-proxy
```

> **Why a fake API key?** Claude Code refuses to start without `ANTHROPIC_API_KEY`. Since Thalamus handles auth via your Cursor token, this value is never sent anywhere. Any non-empty string works.

> **Make it permanent** — add to your shell config so you don't have to set it every time:
> ```bash
> echo 'export ANTHROPIC_BASE_URL=http://localhost:3013' >> ~/.zshrc
> echo 'export ANTHROPIC_API_KEY=thalamus-proxy' >> ~/.zshrc
> source ~/.zshrc
> ```

### Step 5: Launch

```bash
claude
```

That's it. Claude Code is now running on your Cursor subscription. All capabilities work: file editing, bash execution, web search, MCP tools — everything.

### Verify It's Working (Optional)

Send a direct test request:

```bash
curl -s http://localhost:3013/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 50,
    "messages": [{"role": "user", "content": "Say hello in one sentence."}]
  }' | python3 -m json.tool
```

If you see a JSON response with the model's reply, everything is working.

## How It Works

### Protocol Translation

Thalamus translates between Anthropic's Messages API and Cursor's private protobuf-based gRPC API in real time. Requests arrive as standard Anthropic JSON, get encoded into Cursor's protobuf format, streamed over HTTP/2, and the response is decoded back into Anthropic SSE events.

### LTLP: Learn by Doing

Instead of injecting all 40+ tool definitions (27K tokens) into every prompt, Thalamus:

1. **Generates stubs dynamically** from the incoming `tools[]` parameter — one line per tool, no hardcoding
2. **Detects stub calls** when the model tries to use a tool with missing/incomplete arguments
3. **Returns the full schema** as a `tool_result`, giving the model few-shot context
4. **Periodically reminds** the model about available tools every N turns to prevent attention decay

The entire mechanism is transparent — Claude Code sees standard Anthropic responses.

### Continuation Retry

When the model produces text without calling any tool or `task_complete`:

1. Thalamus appends a continuation prompt and re-calls the upstream API
2. If the retry produces tool calls → merged with the original text into one response
3. If the retry produces `task_complete` → returns `stop_reason: end_turn`
4. Safety valve after max retries → falls through as `end_turn`

## Using with Other Tools

Thalamus isn't just for Claude Code — anything that talks to OpenAI or Anthropic APIs can use it:

```bash
# aider (AI pair programming)
export ANTHROPIC_BASE_URL=http://localhost:3013
export ANTHROPIC_API_KEY=thalamus-proxy
aider

# Python openai SDK
import openai
client = openai.OpenAI(base_url="http://localhost:3013/v1", api_key="thalamus-proxy")
response = client.chat.completions.create(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": "Hello"}]
)

# Python anthropic SDK
import anthropic
client = anthropic.Anthropic(base_url="http://localhost:3013", api_key="thalamus-proxy")
message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)

# curl (OpenAI format)
curl http://localhost:3013/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-20250514","messages":[{"role":"user","content":"Hi"}]}'
```

## Configuration

All settings go in `.env` (copy from `.env.example`). Most users only need `CURSOR_TOKEN`.

| Variable | What it does | Default |
|----------|-------------|---------|
| `PORT` | Port Thalamus listens on | `3013` |
| `CURSOR_TOKEN` | Your Cursor auth token (**the only required setting**) | — |
| `CURSOR_CLIENT_VERSION` | Cursor version to impersonate (change if Cursor updates break things) | `2.5.25` |
| `CURSOR_CLOUDFLARE_IP` | IP address for api2.cursor.sh (rarely needs changing) | `104.18.19.125` |
| `CLAUDE_CODE_MODEL_FALLBACK_ENABLED` | Auto-switch to another model on timeout | `true` |
| `CLAUDE_CODE_MAX_MODEL_ATTEMPTS` | How many models to try before giving up | `5` |
| `CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_MS` | How long to wait for first response (ms) | `10000` |
| `CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_ENABLED` | Enable/disable timeout detection | `true` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (includes token status) |
| POST | `/v1/messages` | Anthropic Messages API (primary) |
| POST | `/v1/chat/completions` | OpenAI Chat Completions API |
| GET | `/v1/models` | List available models |
| GET | `/cursor/login` | Initiate PKCE browser login |
| POST | `/token/update` | Update Cursor token |
| GET | `/token/status` | Check current token |

## vs Alternatives

| | Thalamus | Cursor-To-OpenAI | CCProxy | LiteLLM |
|---|---|---|---|---|
| Lazy Tool Loading (LTLP) | ✅ | ❌ | ❌ | ❌ |
| Auto-continuation | ✅ | ❌ | ❌ | ❌ |
| Stub reminders | ✅ | ❌ | ❌ | ❌ |
| Model fallback chain | ✅ | ❌ | Partial | ✅ |
| Anthropic API output | ✅ | ❌ | ❌ | ✅ |
| OpenAI API output | ✅ | ✅ | ✅ | ✅ |
| Cursor → Protobuf | ✅ | ✅ | ❌ | ❌ |
| Works with Claude Code | ✅ | ❌ | ✅ | ✅ |

## Desktop App

> **[Download Thalamus.app (macOS)](https://github.com/guojun21/thalamus/releases/latest/download/Thalamus-macOS.zip)**

A native macOS desktop launcher that wraps Thalamus into a one-click experience:

- **One-click start** — double-click the app icon, backend starts automatically
- **Built-in login** — Cursor PKCE login with automatic token save
- **API test panel** — test model list and send messages with model selection
- **Lightweight** — Swift + WKWebView, ~270KB, no Electron

### Install from Release

1. Download [`Thalamus-macOS.zip`](https://github.com/guojun21/thalamus/releases/latest/download/Thalamus-macOS.zip)
2. Unzip and drag `Thalamus.app` to `/Applications`
3. Double-click to launch

### Build from Source

```bash
cd thalamus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd desktop-app && bash build.sh
```

> **Note:** The app requires Python 3.10+ and thalamus-py dependencies to be installed on your system.

## Architecture

```
thalamus/
├── server.py                  # FastAPI entry point
├── config/
│   ├── fallback_config.py     # Model fallback strategies
│   ├── system_prompt.py       # System prompt injection
│   └── tool_registry.py       # Tool normalization & validation
├── core/
│   ├── cursor_h2_client.py    # HTTP/2 client (api2.cursor.sh)
│   ├── cursor_pkce_login.py   # PKCE browser login flow
│   ├── protobuf_builder.py    # Request protobuf encoding
│   ├── protobuf_frame_parser.py  # Response protobuf decoding
│   └── token_manager.py       # Token persistence & rotation
├── claude_code/
│   ├── pipeline.py            # Main request pipeline (LTLP + continuation + fallback)
│   ├── tool_lazy_loader.py    # Stub generation, schema store, LTLP core
│   ├── tool_prompt_builder.py # Prompt injection & periodic reminders
│   ├── tool_parser.py         # Tool call extraction from text
│   ├── sse_assembler.py       # Anthropic SSE event assembly
│   ├── openai_sse_assembler.py  # OpenAI SSE event assembly
│   └── normalizers.py         # Request/response normalization
├── routes/
│   ├── anthropic_messages.py  # POST /v1/messages
│   ├── openai_chat.py         # POST /v1/chat/completions
│   └── login_routes.py        # PKCE login endpoints
├── proto/
│   ├── cursor_api.proto       # Protobuf schema
│   └── cursor_api_pb2.py      # Generated Python code
└── utils/
    └── structured_logging.py  # Multi-dimensional log partitioning
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Framework | FastAPI + Uvicorn |
| HTTP/2 | httpx, h2 |
| Serialization | protobuf |
| Validation | Pydantic |

## FAQ & Troubleshooting

<details>
<summary><b>Is this free? Do I need to pay anything?</b></summary>

You need a **Cursor subscription** (Pro at $20/month or Business). That's it. You do NOT need an Anthropic API key. Thalamus itself is free and open source.
</details>

<details>
<summary><b>Is this against Cursor's Terms of Service?</b></summary>

Thalamus uses your own authenticated Cursor account to make API calls — the same calls Cursor IDE makes internally. It does not share accounts, bypass rate limits, or redistribute access. Use at your own discretion.
</details>

<details>
<summary><b>Which models can I use?</b></summary>

Whatever models your Cursor subscription includes. Typically: Claude Sonnet 4, Claude Haiku, GPT-4o, GPT-4.1, etc. Run `curl http://localhost:3013/v1/models` to see the full list.
</details>

<details>
<summary><b>Does Claude Code work normally? Can it edit files, run bash, use tools?</b></summary>

Yes. All of Claude Code's capabilities work: file editing (Read/Write/Edit), bash execution, web search, MCP tools, task management — everything. Thalamus translates the protocol transparently; Claude Code doesn't know it's not talking to Anthropic directly.
</details>

<details>
<summary><b>"has_token": false — health check shows no token</b></summary>

Your `CURSOR_TOKEN` is not set or is invalid. Either:
1. Visit `http://localhost:3013/cursor/login` to login via browser, or
2. Check your `.env` file — make sure `CURSOR_TOKEN=` has a value (no quotes needed)
</details>

<details>
<summary><b>Claude Code says "connection refused" or "ECONNREFUSED"</b></summary>

Thalamus is not running. Make sure:
1. `python server.py` is running in a terminal
2. The port matches: default is `3013`
3. Your env vars are set: `ANTHROPIC_BASE_URL=http://localhost:3013`
</details>

<details>
<summary><b>Token expired / "Model name is not valid" errors</b></summary>

Your Cursor token may have expired. Tokens typically last ~60 days. Re-login:
1. Visit `http://localhost:3013/cursor/login`
2. Or extract a fresh token from Cursor IDE's DevTools (Network tab → any request to `api2.cursor.sh` → copy `Authorization` header)
</details>

<details>
<summary><b>Can I use this with tools other than Claude Code?</b></summary>

Yes. Thalamus serves both Anthropic (`/v1/messages`) and OpenAI (`/v1/chat/completions`) formats. You can use it with:
- **aider** — `export ANTHROPIC_BASE_URL=http://localhost:3013`
- **Open WebUI** — set the API base URL in settings
- **Python scripts** — use the `openai` or `anthropic` SDK with custom base URL
- Any tool that supports custom API endpoints
</details>

<details>
<summary><b>How is this different from cursor2api / Cursor-To-OpenAI?</b></summary>

Those projects do basic protocol conversion. Thalamus adds three mechanisms that make Claude Code actually work reliably:
1. **LTLP** — compresses 40+ tool definitions from 27K tokens to 1KB stubs (without this, tool calling often fails)
2. **Auto-continuation** — prevents the model from stopping mid-task when it outputs text without tools
3. **Model fallback** — automatically retries with different models when one is slow/unavailable

Without these, Claude Code frequently breaks: tools don't get called, tasks stop halfway, or the model times out.
</details>

<details>
<summary><b>Windows support?</b></summary>

Thalamus itself runs on Windows (Python + FastAPI). However, Claude Code CLI currently only supports macOS and Linux. If you're on Windows, use WSL2.
</details>

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

[MIT](LICENSE)

---

<details>
<summary><h2>中文说明</h2></summary>

### 这是什么？

**用你的 Cursor 订阅来跑 Claude Code，不需要额外买 Anthropic API key。**

- **Claude Code** 是 Anthropic 出的终端 AI 编程 agent，能自主编辑文件、执行命令、管理项目。但它需要 Anthropic API key（按量付费，很贵）。
- **Cursor** 是 AI 编辑器，订阅后可以用 Claude/GPT 等模型，但只能在 Cursor 编辑器里用。
- **Thalamus** 把两者打通：在本地跑一个代理服务器，伪装成 Anthropic API，实际调用 Cursor 的后端。Claude Code 以为自己在跟 Anthropic 通信，其实用的是你已有的 Cursor 订阅额度。

**丘脑**是大脑中所有感觉信号的中继站——它不产生智能，但让智能可达。这正是本项目的定位：**不是大脑本身，而是通往大脑的门户。**

### 为什么不能直接用其他代理？

其他项目（cursor2api、Cursor-To-OpenAI 等）只做简单的协议转换。但 Claude Code 有 40+ 个工具定义（文件读写、bash 执行、搜索等），Cursor API 不原生支持这些，所以直接转发会导致：

- 工具调不通（模型不知道参数格式）
- 任务做到一半就停了（模型输出文字后被误判为"完成"）
- 模型超时无响应

Thalamus 解决了这三个核心问题：

| 机制 | 解决什么 |
|---|---|
| **🔮 懒加载 Tool 协议 (LTLP)** | 40+ 工具定义（27K tokens）压缩为 1KB 的精简描述，按需加载完整定义，模型通过上下文自动学会正确参数 |
| **🔄 自动续接** | 模型输出纯文字但没执行操作时，自动提醒它继续执行，把文字和操作合并为一个完整响应 |
| **🛡️ 智能模型回退** | 模型响应慢或不可用时，自动切换到下一个可用模型，不需要手动干预 |

### 使用教程

#### 前置条件

| 需要什么 | 为什么 | 怎么检查 |
|---|---|---|
| Python 3.10+ | Thalamus 是 Python 写的 | `python3 --version` |
| Cursor Pro/Business 订阅 | 提供模型访问额度 | 已登录 [cursor.com](https://cursor.com) |
| Node.js 18+ | Claude Code CLI 需要 | `node --version` |
| Claude Code CLI | 要跑的 AI agent | `claude --version`（安装：`npm install -g @anthropic-ai/claude-code`）|

#### 第一步：安装 Thalamus

```bash
git clone https://github.com/guojun21/thalamus.git
cd thalamus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

#### 第二步：获取 Cursor Token

Thalamus 需要你的 Cursor 登录凭证来代你调用 API。两种方式：

**方式 A：浏览器登录（最简单）**

```bash
python server.py                              # 先启动服务
# 浏览器打开 http://localhost:3013/cursor/login
# 用 Cursor 账号登录，token 自动保存
```

**方式 B：从 Cursor IDE 手动提取**

1. 打开 Cursor IDE
2. 打开开发者工具：`Cmd+Shift+I`（Mac）/ `Ctrl+Shift+I`（Windows/Linux）
3. 切到 **Network（网络）** 标签页
4. 在聊天框随便输入点东西，触发一个请求
5. 点击任意一个发往 `api2.cursor.sh` 的请求
6. 找到 `Authorization` 请求头，复制完整值（以 `user_` 开头）
7. 配置：

```bash
cp .env.example .env
# 编辑 .env，粘贴 token：
# CURSOR_TOKEN=user_xxxxx::eyJhbGciOi...
```

> **Token 有效期：** 大约 60 天。过期后会报认证错误，重新获取即可。

#### 第三步：启动 Thalamus

```bash
python server.py
```

看到这个就说明启动成功了：

```
INFO:     Uvicorn running on http://0.0.0.0:3013
```

验证一下：

```bash
curl http://localhost:3013/health
# 期望输出：{"status":"ok","has_token":true}
# 如果 has_token 是 false，说明 token 没配好，回第二步
```

#### 第四步：配置 Claude Code

告诉 Claude Code 连 Thalamus 而不是 Anthropic：

```bash
export ANTHROPIC_BASE_URL=http://localhost:3013
export ANTHROPIC_API_KEY=thalamus-proxy
```

> **为什么要设一个假的 API key？** Claude Code 启动时会检查 `ANTHROPIC_API_KEY` 是否存在，不存在就拒绝启动。这个值不会被发送到任何地方，随便填个非空字符串就行。

> **持久化配置**（不用每次都设）：
> ```bash
> echo 'export ANTHROPIC_BASE_URL=http://localhost:3013' >> ~/.zshrc
> echo 'export ANTHROPIC_API_KEY=thalamus-proxy' >> ~/.zshrc
> source ~/.zshrc
> ```

#### 第五步：启动 Claude Code

```bash
claude
```

搞定。现在 Claude Code 用的就是你的 Cursor 订阅额度。所有功能正常：文件编辑、bash 执行、搜索、MCP 工具——全部可用。

#### 也支持 OpenAI 格式

可以接入任何支持自定义 base URL 的工具（aider、Open WebUI、LangChain 等）：

```bash
export OPENAI_BASE_URL=http://localhost:3013/v1
export OPENAI_API_KEY=thalamus-proxy
```

### 桌面应用

> **[下载 Thalamus.app (macOS)](https://github.com/guojun21/thalamus/releases/latest/download/Thalamus-macOS.zip)**

原生 macOS 桌面启动器，双击即用：

- 自动启动 thalamus-py 后端
- 内置 Cursor 登录（PKCE 认证，Token 自动保存）
- API 测试面板（模型列表 + 消息测试，可切换模型）
- 轻量级：Swift + WKWebView，~270KB，无需 Electron

**从源码构建：**

```bash
cd thalamus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd desktop-app && bash build.sh
```

### 常见问题

**Q: 要花钱吗？**
A: 你需要 Cursor 订阅（Pro $20/月）。不需要 Anthropic API key。Thalamus 本身免费开源。

**Q: 违反 Cursor 服务条款吗？**
A: Thalamus 用的是你自己的 Cursor 账号发起 API 调用，和 Cursor IDE 内部的调用方式一样。不共享账号、不绕过限速、不转售访问权限。请自行判断。

**Q: Token 过期了怎么办？**
A: 重新访问 `http://localhost:3013/cursor/login` 登录，或从 Cursor IDE DevTools 重新提取。

**Q: Windows 能用吗？**
A: Thalamus 本身支持 Windows。但 Claude Code CLI 目前只支持 macOS 和 Linux，Windows 用户请用 WSL2。

</details>
