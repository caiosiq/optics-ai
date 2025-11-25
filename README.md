# AI Optics Agent UI

A fast local web UI for assembling and studying optical systems with an LLM. It enforces strict, parseable JSON responses and provides tools to run code, preview files, and selectively add results back into context.

## Key Features

- Strict JSON-only agent responses with schema validation
- Pre-chat model selection (e.g., GPT-4.1, GPT-5)
- Chat UI that renders three blocks when present: `text`, `code`, `json_file`
- Run code server-side, capture printed output, auto-capture plots, list generated files
- Preview images/JSON/CSV/TXT inline; open full files via download endpoint
- Add code outputs and file snippets as context for the next message
- Lightweight memory: clipped recent messages + session constraints extraction
- Robust debugging: shows raw provider payloads when schema errors occur

## Directory Layout

- `server.py`: Flask server, OpenRouter calls, JSON schema enforcement, code execution, MCP client bootstrap
- `static/index.html`: UI page, header, model modal, context bar, chat
- `static/app.js`: UI logic, send/receive, run code, previews, context chips
- `static/styles.css`: Theme, bubbles, code/text styles, modal, context bar
- `agent_config.json`: Agent model and performance settings; agent-specific role and context
- `openrouter_api.txt`: API key for OpenRouter (do not commit secrets)
- `optics_mcp/`: Local MCP server implemented in Python
  - `optics_server.py`: FastMCP server exposing resources and tools
  - `__init__.py`: Package initializer

## Response Schema

The agent must return a single JSON object with these keys:

- `text`: short natural language reply (string or null)
- `code`: executable snippet (string or null)
- `code_meta`: metadata for code output files (object with `files_expected: string[]`, or null)
- `json_file`: structured optical system data (object or null)

Schema validation is applied via `response_format: json_schema` with strict mode disabled (`strict: false`) for provider compatibility. The schema ensures:

- No extra keys
- `json_file` includes `system`, `elements`, `spacing_mm`, `wavelength_nm`
- `elements` each include `type`, `material`, `radius_front_mm`, `radius_back_mm`, `thickness_mm`

## Guard Rails and Agent Context

- Guard rails are provided via the MCP resource `resource://optics-guardrails` and referenced in the system prompt.
- Agent-specific role and context live in `agent_config.json` under:
  - `agent_role`: e.g., "Optics Chat Agent"
  - `agent_context`: concise lines describing this agent’s domain and output preferences

## Running Locally

1. Install dependencies: `pip install -r requirements.txt`
2. Put your OpenRouter key in `agent-ui/openrouter_api.txt`
3. Start server: `python server.py`
4. Open: `http://127.0.0.1:8000/`

## Using the UI

- Choose a Reviewer Model in the modal; it appears in the header
- Type a message and send
- The assistant returns JSON that the UI renders as blocks:
  - `text`: normal bubble
  - `code`: shows snippet and a “Run Code” button
  - `json_file`: pretty-printed optical system configuration
- After running code:
  - Output text appears and you can “Add output to context”
  - Generated files list with inline previews and an “Add `<file>` to context” button
- Context chips show what will be included in the next message; remove as needed

## Code Execution

- Server runs code in a temp directory per run (`tmp_runs/<uuid>`)
- Intercepts `plt.show()` to capture plots as PNGs and returns them inline
- Returns JSON:
  - `ok`: boolean
  - `output`: combined stdout/stderr text
  - `images`: base64 PNGs
  - `files`: paths of created files
- Download created files via `/download?path=...` (restricted to allowed directories)

## Context Memory and Efficiency

- Clipped rolling history (configurable): `context_window_messages` and `max_message_chars`
- Session constraints extractor gathers concise parameter lines from recent user messages
- Additional run context is injected via `extra_context` (UI-provided)
- All additions are clipped by `max_context_addition_chars` to cap token usage
- The system prompt is thin and references MCP resources rather than inlining schema and guard rails

## Streaming Pipeline (Drafter & Reviewer)

- Toggle “Use streaming drafter/reviewer” in the modal to enable the low-latency pipeline.
- Select a Drafter Model (fast inference; default: `openai/gpt-4o-mini`). The drafter:
  - Produces Python code immediately without strict JSON formatting.
  - Streams draft events quickly for latency, but the UI suppresses drafter code display and shows only the Reviewer’s final code.
- Reviewer Model (the primary model selected at the top of the modal):
  - Validates physics and structure and returns strict JSON.
  - Uses MCP resources for schema (`resource://ui-output-format`) and guardrails (`resource://optics-guardrails`).
- The header shows both when streaming is enabled: `reviewer: <model> • drafter: <model>`.

- Drafting heuristics:
  - The drafter only runs when your message appears to request code or simulation (keywords include “simulate”, “plot”, “code”, “python”, “diffraction”, “optics”, etc.).
  - Simple greetings or non-code questions skip drafting; the Reviewer returns a concise text response.

Notes:
- Model IDs must be valid OpenRouter identifiers. Invalid IDs cause a 400 and will stream an error.
- If unsure, use `openai/gpt-4o-mini` for the drafter and any of the GPT-4.1 family for the reviewer. The drafter also supports `minimax/minimax-m2`.

## MCP Architecture and Usage

- **Why MCP**

  - Defer large context loading by exposing files and rules as resources the model can read only when needed
  - Keep prompts small and fast by referencing resources (`resource://...`) instead of inlining long texts
  - Provide server-side validation tools and structured outputs backed by Pydantic models
  - Avoid namespace shadowing by using a local package name `optics_mcp`
- **Server Components**

  - `optics_mcp/optics_server.py` runs a FastMCP server exposing:
    - `resource://ui-output-format`: Returns `OpticsAgentResponse.model_json_schema()` (Pydantic model) used for response formatting
    - `resource://optics-guardrails`: Returns guard rules for JSON-only output and runnable code expectations
    - `file://{path}`: Reads small files from safe directories (`saved_json`, `tmp_runs`) for on-demand context
    - `validate_ui_output` tool: Validates candidate JSON against `OpticsAgentResponse`
  - `server.py` boots an MCP client via stdio: `Client(script_path)` where `script_path` points to `optics_mcp/optics_server.py`
- **Response Formatting**

  - `server.py` builds the system prompt and message list, then calls OpenRouter with `response_format: json_schema`
  - The JSON Schema comes from `OpticsAgentResponse.model_json_schema()`; on import failure, a minimal valid schema is used locally
  - Strict mode is disabled (`strict: false`) for provider compatibility; local validation and a corrective retry are applied when needed
  - The server performs local Pydantic validation and retries with a corrective nudge on errors
- **Resources vs Prompt Text**

  - The prompt references `resource://ui-output-format` and `resource://optics-guardrails` so the model knows where to read format and rules
  - Files are passed as metadata and read via `file://{path}` only when required; this saves tokens and improves performance
- **Shadowing Avoidance**

  - The local MCP package was renamed from `mcp` to `optics_mcp` to prevent import conflicts with the official `mcp` library used by FastMCP

## Attaching Files for Context

- Place files under `agent-ui/saved_json` or outputs under `agent-ui/tmp_runs`
- Provide the file path in the UI context; the model is instructed it can read via `file://{path}` when necessary
- Large files are rejected by the resource to prevent excessive token usage; prefer summaries or targeted reads

## Configuration (`pipeline_context.json`)

- `drafter`: controls the drafter’s system, history inclusion, previous-run context, trigger keywords, and clipping rules
- `reviewer`: controls the reviewer’s system, history inclusion, previous-run context, session constraints, and clipping rules
- `models`: `drafter_model`, `reviewer_model`
- `llm`: reviewer-specific `max_tokens_reviewer`, `temperature_reviewer`, `reasoning_effort_reviewer`

### Model precedence

- The UI selection takes priority for the Reviewer and Drafter when provided.
- If not supplied by the UI, the server uses `pipeline_context.json` values.

## Debugging

- If the model returns invalid JSON, the server retries with compressed context and a clarifying system nudge
- On final failure, `/chat` returns:
  - `error`: message
  - `raw_message`: the model’s raw content
  - `raw_response`: provider payload for inspection
- The UI displays both as code blocks below the error bubble

## Security Notes

- Do not commit `openrouter_api.txt` or any secrets
- Code execution is sandboxed minimally and only returns captured output/images/files. Review code before adding more capabilities

## Extending

- Add more element fields to `json_file` schema as your optics pipeline evolves
- Add SSE streaming for partial JSON if desired
- Add lightweight retrieval to include top reference snippets when needed

## Troubleshooting

- If GPT-5 truncates to reasoning tokens without JSON:
  - Lower reasoning effort, reduce temperature, raise `max_tokens`
  - Reduce context sizes in `agent_config.json`
- Codes failing due to arguments:
  - The guard rails require runnable code without CLI args; the assistant should request parameters in `text` and provide defaults in `code`
## Multi‑Agent Architecture

- Thinker → Drafter → Reviewer runs in streaming mode by default:
  - Thinker: produces a concise physics plan (constraints, formulas, constants, allowed libraries). No code.
  - Drafter: follows the plan and writes raw Python only; agentic outputs are handled (tool_calls, reasoning) and code is extracted.
  - Reviewer: validates physics and syntax, returns strict JSON, and applies corrections as needed.
- Intent gating avoids triggering Thinker/Drafter on greetings; the pipeline uses a fast reviewer path for simple messages.
- Header shows `reviewer: <model> • drafter: <model>`.

## MCP Overview

- Server: `optics_mcp/optics_server.py` provides resources and tools used by the pipeline.
- Resources:
  - `resource://ui-output-format` → JSON Schema from `OpticsAgentResponse` (Pydantic).
  - `resource://optics-guardrails` → rules for JSON‑only output and runnable code.
  - `file://{path}` → safe file reads from `saved_json` and `tmp_runs` (on‑demand context).
- Tools:
  - `validate_ui_output(candidate)` → validates a candidate JSON against `OpticsAgentResponse`.
  - `exec_python_sandbox(code)` → executes Python in a sandboxed, in‑process environment; captures text and images (PNG base64).
- The UI and server reference resources in prompts to keep messages small; tools are invoked by the server for validation and execution.

## Runtime Flow

1. Gating: If the message does not look like a coding task, Thinker/Drafter are skipped and a fast reviewer returns a concise response.
2. Thinker: Builds `thinker_messages` from `pipeline_context.json.thinker.system` and user input; returns a plan string.
3. Drafter: Builds `drafter_messages` from the drafter system + history + plan + user request; inserts an import prefill (`import numpy as np`) to reduce “thinking”. Extracts code even when models return tool_calls.
4. SSE: Draft event streams code quickly to the UI (UI hides draft by default, with compact toggles to reveal draft code/raw).
5. Reviewer: Receives the draft and user request; validates physics and syntax; returns strict JSON with final `text`, `code`, `code_meta`, `json_file`. If code fails locally, the server sends a corrective message and retries once.
6. Logs: `tmp_runs/<YYYYMMDD‑HHMMSS>-<uuid>/interaction.txt` records the prompts, raw replies and final parsed output.

## Configuration Keys (`pipeline_context.json`)

- `thinker` → `system`, `include_history_messages`, `clip_user_chars`, `clip_extra_context_chars`
- `drafter` → `system` (raw code only; no tools/markdown), `include_history_messages`, `include_previous_run_context`, `keywords_trigger`, `clip_user_chars`, `clip_extra_context_chars`
- `reviewer` → strict JSON system, `include_history_messages`, `include_previous_run_context`, `include_session_constraints`, `schema_resource`, `guardrails_resource`, clipping
- `models` → `thinker_model`, `drafter_model`, `reviewer_model`, `fast_reviewer_model`
- `llm` → `max_tokens_thinker`, `temperature_thinker`, `max_tokens_drafter`, `temperature_drafter`, `max_tokens_reviewer`, `temperature_reviewer`, `reasoning_effort_reviewer`, and small/fast reviewer overrides (`max_tokens_reviewer_small`, `temperature_reviewer_small`, `reasoning_effort_reviewer_small`)

## Endpoints

- `POST /chat` → single‑pass reviewer JSON response (strict disabled; local validation/one retry).
- `POST /chat_flow` → streaming pipeline; emits `event: draft` (draft code/raw) and `event: review` (final JSON).
- `POST /run_code` → executes code via MCP `exec_python_sandbox` and returns `ok`, `output`, `images`.
- `GET /config_models` → returns pipeline models: `thinker_model`, `drafter_model`, `reviewer_model` (UI uses this to show the active drafter).
- `GET /download?path=...` → safe file preview/download.
- `GET /test_response` → sample response for UI testing.

## UI Editing & Context

- Code blocks are editable inline; click “Edit Code” to toggle contentEditable on the code rows.
- “Run Code” executes the currently visible content in the block.
- “Add to context” adds the current edited code into the next request.
- Draft toggles (“Show Drafter Code”, “Show Draft Raw Reply”) are compact pill buttons to avoid visual clutter.
