# WebGIS Agent - CLI AI Coding Assistant

A command-line AI coding agent for the WebGIS-AI project, built with TypeScript/Node.js. Based on architectural patterns from Claude Code and MiniCode.

## Quick Start

```bash
# 1. Install dependencies
cd agent
npm install

# 2. Configure API key
cp .env.example .env
# Edit .env and set MIMO_API_KEY

# 3. Run
npm run dev           # Interactive mode (tsx, no build needed)
npm run build && npm start  # Compiled mode
```

## Usage

```bash
# Interactive REPL
npx tsx src/index.ts chat

# Single-shot mode (send message, get response, exit)
npx tsx src/index.ts chat -m "read package.json"

# Resume a session
npx tsx src/index.ts chat -s <session-id>

# List past sessions
npx tsx src/index.ts sessions

# Override model or backend
npx tsx src/index.ts chat --model mimo-v2.5 --backend http://localhost:18999

# Auto-approve all tool calls (no confirmation prompts)
npx tsx src/index.ts chat --auto-approve
```

## Slash Commands (inside REPL)

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/tools` | List all registered tools |
| `/clear` | Clear conversation history |
| `/compact` | Force context compression |
| `/quit` | Exit the agent |

## Architecture

```
Terminal User
    |
    v
[TUI (readline + chalk)]
    |
    v
[Agent Loop (async generator)]
    |  - iterates: model call -> tool execution -> repeat
    |  - context compression (snip + auto-compact)
    |  - permission checks per tool
    v
[Model Adapter (MiMo API)]
    |
    v
[Tool Registry]
    |-- Core Tools (read, write, edit, bash, grep, glob, web-fetch, ask-user)
    |-- GIS Tools  --> HTTP --> Python Backend (port 18999)
```

### Key Files

| File | Purpose |
|------|---------|
| `src/index.ts` | CLI entry point (Commander.js), wires everything |
| `src/agent-loop.ts` | Core agentic loop: model call -> tool execution -> repeat |
| `src/model-adapter.ts` | MiMo API client (OpenAI Chat Completions compatible) |
| `src/tool.ts` | Tool interface, registry, and execution dispatch |
| `src/prompt.ts` | System prompt builder (static identity + dynamic context) |
| `src/permissions.ts` | Per-tool allow/deny/confirm permission rules |
| `src/context.ts` | Context compression: snip compact + LLM auto-compact |
| `src/tui.ts` | Terminal UI with colored output |
| `src/session.ts` | JSONL session persistence with resume |
| `src/config.ts` | Environment variable loading and validation |
| `src/tools/*.ts` | Individual tool implementations |

### Design Patterns (from Claude Code / MiniCode)

1. **Async Generator Agent Loop** - The loop calls the model, checks for tool calls, executes them, and repeats until a final text response. Same pattern as Claude Code's `query.ts`.

2. **Unified Tool Contract** - Every tool has a `name`, `description`, JSON Schema `parameters`, and an `execute()` function. The registry provides `getDefinitions()` for the model API and `execute()` for dispatch.

3. **Progress/Final Protocol** - The model prefixes intermediate text with `[progress]` and omits it for final answers. This prevents premature termination.

4. **Snip Compact** - Large tool outputs are truncated to prevent context overflow. Shows first 30 and last 20 lines.

5. **Auto-Compact** - When estimated tokens exceed 60k, older messages are summarized by the LLM and replaced with a summary.

6. **Session Persistence** - Messages are appended to JSONL files. Sessions can be resumed by ID.

7. **Permission Cascade** - Read-only tools are auto-allowed. Write tools require confirmation. User can approve per-session.

## Tools

### Core Tools (8)

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers. Supports offset/limit. |
| `write_file` | Write content to a file. Creates parent directories. |
| `edit_file` | Search-and-replace edit. Shows diff preview. |
| `list_files` | Glob-based file listing. |
| `grep_files` | Content search (ripgrep with Node.js fallback). |
| `run_command` | Execute shell commands with timeout. |
| `web_fetch` | Fetch URL and convert HTML to markdown. |
| `ask_user` | Ask the user a question (pauses loop). |

### GIS Tools (13)

These tools call the WebGIS Python backend via HTTP. The backend must be running on the configured URL (default: `http://127.0.0.1:18999`).

| Tool | Endpoint | Description |
|------|----------|-------------|
| `gis_health` | `GET /health` | Check backend connectivity |
| `gis_list_projects` | `GET /projects` | List GIS projects |
| `gis_create_project` | `POST /projects` | Create new project |
| `gis_get_project` | `GET /projects/{id}` | Get project details |
| `gis_list_layers` | `GET /layers?project_id=` | List project layers |
| `gis_submit_workflow` | `POST /workflow/submit` | Submit GIS analysis workflow |
| `gis_workflow_status` | `GET /workflow/{id}` | Poll workflow status |
| `gis_list_templates` | `GET /workflow/templates` | List GIS templates |
| `gis_search_poi` | `POST /search/poi` | Search POI by keyword |
| `gis_ask_assistant` | `POST /assistant/messages` | Delegate to WebGIS AI assistant |
| `gis_list_catalog` | `GET /datasets/catalog` | List OneMap datasets |
| `gis_add_catalog_layer` | `POST /datasets/catalog/layers` | Add dataset as layer |
| `gis_kb_search` | `GET /kb/search` | Search geography knowledge base |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MIMO_API_KEY` | (required) | MiMo API key |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | MiMo API base URL |
| `MIMO_MODEL` | `mimo-v2.5-pro` | Model identifier |
| `WEBGIS_BACKEND_URL` | `http://127.0.0.1:18999` | WebGIS backend URL |
| `AGENT_MAX_TURNS` | `50` | Max agent loop turns per message |
| `AGENT_MAX_TOKENS` | `4096` | Max completion tokens per model call |
| `AGENT_TEMPERATURE` | `0.2` | Sampling temperature |
| `AGENT_AUTO_APPROVE` | `true` | Skip permission prompts |

### .env File

Copy `.env.example` to `.env` and fill in your API key:

```env
MIMO_API_KEY=your-key-here
```

## Session Storage

Sessions are stored in `~/.webgis-agent/sessions/`:

```
~/.webgis-agent/sessions/
  index.json          # Session index with metadata
  <session-id>.jsonl  # Append-only message log per session
```

Each line in a JSONL file is a JSON object:
```json
{"type":"message","ts":"2026-06-13T10:00:00Z","data":{"role":"user","content":"hello"}}
{"type":"message","ts":"2026-06-13T10:00:01Z","data":{"role":"assistant","content":"Hi!"}}
```

## Development

```bash
# Type check
npx tsc --noEmit

# Build
npm run build

# Run with tsx (no build needed)
npm run dev

# Run tests (if vitest is configured)
npm test
```

## Relationship to WebGIS Backend

This agent is a **CLI frontend** that:

1. Uses the same OpenAI-compatible API format as the existing backend's LLM client
2. Calls the backend's REST API for GIS operations (same endpoints as the web frontend)
3. Works standalone for code editing tasks (no backend needed)
4. Adds GIS awareness when the backend is running

The existing web frontend and backend services continue to work independently. The agent is an additional interface, not a replacement.
