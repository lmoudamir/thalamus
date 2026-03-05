# thalamus-py

**Claude Code 专用 Cursor API 翻译层（Python 版）** — 将 Cursor API 伪装成 Anthropic 原生 API，让 Claude Code 通过 `/v1/messages` 透明接入 Cursor 后端。

```
Claude Code  →  /v1/messages (Anthropic 格式)  →  thalamus-py  →  Cursor API (api2.cursor.sh)
                                                       ↑
                                             协议翻译 / prompt 注入 / protobuf 编解码
```

🔗 **GitHub**: https://github.com/guojun21/thalamus-py (Private)

---

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | **3.10+**（使用了 `match/case`、`list[str]` 类型注解等语法） |
| pip | 最新即可 |
| 网络 | 能访问 `api2.cursor.sh`（通过 Cloudflare） |

---

## 快速开始

### 1. 创建虚拟环境并安装依赖

```bash
cd thalamus-py

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

依赖清单（`requirements.txt`）：

| 包名 | 用途 |
|------|------|
| fastapi | Web 框架 |
| uvicorn | ASGI 服务器 |
| httpx[http2] | HTTP/2 客户端，连接 Cursor API |
| h2 | HTTP/2 底层协议支持 |
| protobuf | Cursor API 的 protobuf 编解码 |
| python-dotenv | 读取 `.env` 文件 |
| pydantic | 请求/响应模型验证 |

### 2. 配置环境变量

`.env` 已提交到仓库，克隆即可用。如需修改：

```bash
vim .env
```

### 3. 获取 Cursor Token

必须配置 `CURSOR_TOKEN` 才能调用 Cursor API，获取方式任选其一：

**方式 A：PKCE 浏览器登录**

启动服务后访问 `/cursor/login`，按提示在浏览器完成 Cursor 登录，token 自动写入 `.env`。

**方式 B：手动设置**

从 Cursor IDE 的请求中抓取 token，写入 `.env`：

```
CURSOR_TOKEN=user_xxxxx::eyJhbGciOi...
```

或通过 API：

```bash
curl -X POST http://localhost:3013/token/update \
  -H "Content-Type: application/json" \
  -d '{"token":"user_xxxxx::eyJhbGciOi..."}'
```

### 4. 启动服务

```bash
python server.py
```

或用 uvicorn 直接启动（支持 reload）：

```bash
uvicorn server:app --host 0.0.0.0 --port 3013 --reload
```

服务默认监听 `http://0.0.0.0:3013`。

### 5. 验证

```bash
# 健康检查
curl http://localhost:3013/health
# {"status":"ok","has_token":true}

# 测试聊天
curl -X POST http://localhost:3013/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -H "X-API-Key: any" \
  -d '{"model":"claude-3.5-sonnet","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}'
```

---

## 配合 Claude Code 使用

```bash
export ANTHROPIC_BASE_URL=http://localhost:3013
export ANTHROPIC_API_KEY=thalamus-proxy
claude
```

---

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PORT` | 服务监听端口 | `3013` |
| `CURSOR_TOKEN` | Cursor 认证 token（**必须配置**） | 空 |
| `CURSOR_CLIENT_VERSION` | 模拟的 Cursor 客户端版本号 | `2.5.25` |
| `CURSOR_CLOUDFLARE_IP` | api2.cursor.sh 的 Cloudflare IP | `104.18.19.125` |
| `CLAUDE_CODE_MODEL_FALLBACK_ENABLED` | 模型回退开关 | `true` |
| `CLAUDE_CODE_MAX_MODEL_ATTEMPTS` | 回退最大尝试次数 | `5` |
| `CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_MS` | 首 token 超时（毫秒） | `10000` |
| `CLAUDE_CODE_FIRST_TOKEN_TIMEOUT_ENABLED` | 是否启用首 token 超时 | `true` |

---

## 项目结构

```
thalamus-py/
├── server.py                  # 主入口，FastAPI 应用
├── requirements.txt           # Python 依赖
├── .env                       # 环境变量（已提交）
├── .env.example               # 环境变量模板
│
├── config/                    # 配置
│   ├── fallback_config.py     #   模型回退策略
│   ├── system_prompt.py       #   系统提示注入
│   ├── tool_mapping.py        #   Cursor ↔ Claude Code 工具名映射
│   └── tool_registry.py       #   工具注册与规范化
│
├── core/                      # 核心逻辑
│   ├── cursor_h2_client.py    #   HTTP/2 客户端（连接 api2.cursor.sh）
│   ├── cursor_pkce_login.py   #   PKCE 登录流程
│   ├── protobuf_builder.py    #   请求 protobuf 构建
│   ├── protobuf_frame_parser.py   # 响应 protobuf 解析
│   ├── token_manager.py       #   Token 管理与持久化
│   └── unified_request.py     #   统一请求处理
│
├── claude_code/               # Claude Code 适配
│   ├── pipeline.py            #   主请求处理流水线
│   ├── sse_assembler.py       #   SSE 流式响应组装
│   ├── normalizers.py         #   请求/响应规范化
│   ├── tool_parser.py         #   工具调用解析
│   └── tool_prompt_builder.py #   工具提示构建
│
├── routes/                    # API 路由
│   ├── anthropic_messages.py  #   POST /v1/messages
│   ├── openai_chat.py         #   POST /v1/chat/completions
│   ├── model_routes.py        #   GET /v1/models
│   ├── token_routes.py        #   Token CRUD
│   └── login_routes.py        #   PKCE 登录
│
├── proto/                     # Protobuf
│   ├── cursor_api.proto       #   schema 定义
│   └── cursor_api_pb2.py      #   已生成的 Python 代码（无需重新编译）
│
├── utils/                     # 工具函数
├── tests/                     # 测试
├── integration-tests/         # 集成测试
├── reference/                 # 参考实现与文档
├── experiment_*.py            # 实验脚本
└── logs/                      # 运行日志
```

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（含 token 状态） |
| GET | `/api/hello` | CC SDK 连通性检查 |
| GET | `/v1/oauth/hello` | CC SDK 认证健康检查 |
| POST | `/v1/messages` | Anthropic Messages API（主要端点） |
| POST | `/v1/chat/completions` | OpenAI 兼容聊天接口 |
| GET | `/v1/models` | 模型列表 |
| GET | `/cursor/login` | PKCE 登录 URL |
| GET | `/cursor/poll` | 轮询登录 token |
| GET | `/token/status` | 查看当前 token 状态 |
| POST | `/token/update` | 更新 token |
| DELETE | `/token` | 清除 token |
| POST | `/v1/messages/count_tokens` | Token 计数（CC SDK 用，返回 dummy） |

---

## Protobuf

`proto/cursor_api_pb2.py` 已提交到仓库，日常使用**无需重新编译**。

仅在修改 `proto/cursor_api.proto` 后才需要：

```bash
protoc --python_out=proto proto/cursor_api.proto
```

---

## 与 Node.js 版的关系

本项目是 [Thalamus](https://github.com/guojun21/Thalamus)（Node.js 版）的 Python 重写，功能对等。两者可独立运行，默认端口不同（Node: 3011, Python: 3013）。
