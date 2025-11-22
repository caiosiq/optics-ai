### Optics Agent Guardrails

1. JSON-only responses; no markdown, no extra prose outside the JSON object.
2. Numeric values must be computed inside the `code` block and printed; do not invent numbers.
3. If parameters are missing, ask for them in `text`; avoid numeric claims until provided.
4. Code must run as-is without CLI args or interactive input (`argparse`, `sys.argv`, `input()` are disallowed). Provide safe defaults.
5. Prefer Python unless the user requests otherwise; use SI units or state units explicitly.
6. Only safe local file I/O; list generated files via `code_meta.files_expected` and write outputs to simple filenames.