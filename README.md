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
- `agent_config.json`: Agent model, guard rails, specialist context, performance settings
- `openrouter_api.txt`: API key for OpenRouter (do not commit secrets)

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

## Guard Rails and Optics Context
Defined in `agent_config.json` and injected by `server.py`:
- JSON-only responses, no markdown or extra prose
- No invented numeric values; numbers must be computed in `code` and printed
- If parameters are missing, ask in `text` and avoid numeric claims
- Codes must run as-is: do not use command-line args (`argparse`, `sys.argv`) or `input()`
- Prefer Python unless the user requests otherwise
- Use SI units or clearly state units

## Running Locally
1. Install dependencies: `pip install flask requests matplotlib`
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

## Configuration (`agent_config.json`)
- `model`: default model if not set by UI
- `context_window_messages`: number of prior messages to include
- `max_message_chars`: characters per message when clipping
- `session_constraints_enabled`: enable concise constraints injection
- `max_constraints`: max lines extracted for constraints
- `max_context_addition_chars`: clip length for extra run context
- `max_tokens`: token budget per request (server may raise on truncation retries)
- `reasoning_effort`: provider hint to reduce reasoning verbosity (e.g., `low`)
- `temperature`: generation determinism (lower is more concise)

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

