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
- `server.py`: Flask server, OpenRouter calls, JSON schema enforcement, code execution
- `static/index.html`: UI page, header, model modal, context bar, chat
- `static/app.js`: UI logic, send/receive, run code, previews, context chips
- `static/styles.css`: Theme, bubbles, code/text styles, modal, context bar
- `agent_config.json`: Agent model and performance settings; agent-specific role and context
- `openrouter_api.txt`: API key for OpenRouter (do not commit secrets)
- `mcp/`: Local MCP-like layer
  - `ui_output_format.json`: JSON Schema for responses
  - `ui_output_examples.json`: Examples of valid responses
  - `optics_guardrails.md`: Long-lived guard rails and behavior rules
  - `validator.py`: Loads resources and validates candidate outputs

## Response Schema
The agent must return a single JSON object with these keys:
- `text`: short natural language reply (string or null)
- `code`: executable snippet (string or null)
- `code_meta`: metadata for code output files (object with `files_expected: string[]`, or null)
- `json_file`: structured optical system data (object or null)

Strict validation is applied via `response_format: json_schema`. The schema ensures:
- No extra keys
- `json_file` includes `system`, `elements`, `spacing_mm`, `wavelength_nm`
- `elements` each include `type`, `material`, `radius_front_mm`, `radius_back_mm`, `thickness_mm`

## Guard Rails and Agent Context
- Guard rails live in `mcp/optics_guardrails.md` and are referenced by a thin system prompt.
- Agent-specific role and context live in `agent_config.json` under:
  - `agent_role`: e.g., "Optics Chat Agent"
  - `agent_context`: concise lines describing this agent’s domain and output preferences

## Running Locally
1. Install dependencies: `pip install -r requirements.txt`
2. Put your OpenRouter key in `agent-ui/openrouter_api.txt`
3. Start server: `python server.py`
4. Open: `http://127.0.0.1:8000/`

## Using the UI
- Choose a model in the modal; it appears in the header
- Type a message and send
- The assistant returns JSON that the UI renders as blocks:
  - `text`: normal bubble
  - `code`: shows snippet and a “Run Code” button
  - `json_file`: pretty-printed optical system configuration
- After running code:
  - Output text appears and you can “Add output to context”
  - Generated files list with inline previews and an “Add <file> to context” button
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

## Configuration (`agent_config.json`)
- `default_model`, `temperature`, `reasoning_effort`, `max_tokens`
- `context_window_messages`, `max_message_chars`
- `session_constraints_enabled`, `max_constraints`, `max_context_addition_chars`
- `agent_role`, `agent_context`

### Model precedence
- The UI selection takes priority and is sent with each request.
- `default_model` is only used as a fallback when the UI does not supply a model (e.g., headless calls or tests).

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

