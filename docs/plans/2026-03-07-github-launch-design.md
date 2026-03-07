# Thalamus — GitHub Launch Design

> Date: 2026-03-07
> Status: Approved

## 1. Positioning

**Thalamus** is a smart local proxy that lets **Claude Code** transparently use **Cursor's models** — with enhanced tool calling, auto-continuation, and model fallback.

**Tagline:** *"Not the mind. The gateway to it."*

**Core differentiators vs competitors:**

| Feature | Thalamus | Cursor-To-OpenAI | CCProxy | LiteLLM |
|---------|----------|-------------------|---------|---------|
| Lazy Tool Loading (LTLP) | Yes | No | No | No |
| Auto-continuation (task_complete) | Yes | No | No | No |
| Periodic stub reminders | Yes | No | No | No |
| Model fallback chain | Yes | No | Partial | Yes |
| Protobuf ↔ Anthropic translation | Yes | OpenAI only | No | N/A |
| Dual API (Anthropic + OpenAI) | Yes | OpenAI only | OpenAI | Yes |

## 2. Repository

| Field | Value |
|-------|-------|
| Name | `thalamus` |
| Owner | `guojun21` (or new org TBD) |
| Description | `Smart proxy that lets Claude Code use Cursor's models — with lazy tool loading, auto-continuation & model fallback` |
| Topics | `claude-code`, `cursor`, `llm-proxy`, `tool-calling`, `anthropic`, `openai-compatible`, `ai-coding`, `cursor-api`, `function-calling`, `model-fallback` |
| License | MIT |
| Visibility | Public |

**Why a new repo (not rename):** The old `guojun21/thalamus-py` has `.env` with real Cursor JWT tokens in git history. A clean repo avoids credential leakage entirely.

## 3. Security Cleanup

Before any code enters the new repo:

1. `.env` → `.env.example` with placeholder values only
2. `.gitignore` must include `.env`, `logs/`, `*.db`
3. Audit all files for hardcoded tokens/keys (grep for JWT patterns, `eyJ`, `sk-`, `Bearer`)
4. `core/token_manager.py` — verify no default real tokens
5. Remove `reference/` directory (already gitignored but verify)

## 4. Logo

- **Style:** Multi-faceted crystalline polyhedron (purple-to-gold gradient) with light refraction
- **Symbolism:** Single input beam → crystal relay → multiple output beams = protocol translation
- **Files:** `assets/logo.png` (square, transparent bg)
- **Color palette:** Deep purple (#5B21B6) → Amber/Gold (#D97706), platinum input beam

## 5. README Structure

```
┌─ Logo + "THALAMUS" ─────────────────────────────────┐
│  "Not the mind. The gateway to it."                  │
│  Badges: [Python] [License:MIT] [Stars] [Issues]     │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ## What is Thalamus?                                │
│  One paragraph + ASCII architecture diagram          │
│                                                      │
│  ## Key Features                                     │
│  Three pillars with icons:                           │
│  - 🔮 Lazy Tool Loading (LTLP)                      │
│  - 🔄 Auto-Continuation                             │
│  - 🛡️ Smart Model Fallback                          │
│                                                      │
│  ## Quick Start                                      │
│  3 steps: clone → install → run                      │
│                                                      │
│  ## How It Works                                     │
│  Brief explanation of the three mechanisms           │
│                                                      │
│  ## Configuration                                    │
│  Environment variables table                         │
│                                                      │
│  ## API Endpoints                                    │
│  /v1/messages + /v1/chat/completions                 │
│                                                      │
│  ## vs Alternatives                                  │
│  Comparison table                                    │
│                                                      │
│  ## Architecture                                     │
│  Module diagram                                      │
│                                                      │
│  ## Contributing                                     │
│  ## License                                          │
│  ## 中文说明                                          │
│  Collapsible Chinese section                         │
└──────────────────────────────────────────────────────┘
```

## 6. SEO Strategy

**Target search keywords** (embedded in description, README, topics):

Primary:
- `claude code proxy`
- `cursor api proxy`
- `claude code cursor`
- `llm tool calling proxy`

Secondary:
- `cursor openai compatible`
- `anthropic api proxy`
- `claude code bridge`
- `ai coding agent proxy`
- `function calling enhancement`

**Keyword placement:**
- Repo description: hits "Claude Code", "Cursor", "proxy", "tool loading"
- Topics: 10 tags covering all primary/secondary keywords
- README H2 headings: contain searchable terms
- README first paragraph: keyword-dense but natural

## 7. Implementation Steps

1. Create `.env.example` from `.env` (replace real values with placeholders)
2. Update `.gitignore` (add `.env`)
3. Copy logo to `assets/`
4. Write full README.md
5. Create new GitHub repo `thalamus`
6. Push clean codebase (no `.env`, no git history with tokens)
7. Configure repo settings (description, topics, license)
