
# 🔭 AI Optics Agent UI

**A high-performance, local workspace for designing and simulating optical systems.**

This tool orchestrates a multi-agent AI pipeline to solve physics problems. It separates **reasoning** (Physics) from **implementation** (Python Code) to generate rigorous, runnable simulations. It enforces strict JSON outputs, allowing the UI to render interactive elements, execute code locally, and visualize results instantly.

---

## 🚀 Quick Start

1. **Install Dependencies**
   **Bash**

   ```
   pip install -r requirements.txt
   ```
2. Configure API
   Paste your OpenRouter API key into openrouter_api.txt (ensure this file is git-ignored).
3. **Run the Server**
   **Bash**

   ```
   python server.py
   ```
4. Open the UI
   Navigate to http://127.0.0.1:8000/ in your browser.

---

## 🧠 How It Works: The "Thinker-Drafter-Reviewer" Pipeline

Unlike standard chat interfaces, this agent does not just "guess" code. When you ask for a simulation, it triggers a specialized three-step chain:

1. **🤔 The Thinker (Physicist)**
   * **Role:** Analyzes your request to determine the physical regime (e.g., Geometric Optics vs. Scalar Diffraction).
   * **Output:** A rigorous "Physics Blueprint" listing formulas, constants, and constraints (e.g., "Use Round-Trip ABCD Matrix"). It writes  **no code** .
   * *Model:* Fast Reasoning (e.g., Gemini 1.5 Flash).
2. **💻 The Drafter (Scientific Coder)**
   * **Role:** Translates the Blueprint into efficient Python code.
   * **Output:** Raw, runnable Python (using `numpy`, `scipy`, `matplotlib`).
   * *Model:* Fast Coding (e.g., Gemini 1.5 Flash or Grok-Beta).
3. **🔎 The Reviewer (QA Engineer)**
   * **Role:** Validates the physics and syntax.
   * **Action:** If the Drafter used the wrong matrix order, the Reviewer fixes it.
   * **Output:** A structured JSON object containing the final code, explanation, and system parameters.
   * *Model:* High Intelligence (e.g., GPT-4o).

*(Note: For simple non-coding questions, the pipeline skips the first two steps for speed.)*

---

## ✨ Key Features

* **Structured Output:** Agents must return strict JSON. The UI separates natural language, code, and data tables automatically.
* **Local Code Execution:**
  * Run generated simulations server-side in a sandbox.
  * Auto-captures `plt.show()` plots and displays them inline.
  * Auto-lists generated files (CSV, TXT) for download or context injection.
* **Smart Context Memory:**
  * **Session Constraints:** Automatically extracts key numbers (wavelengths, radii) from your chat history to keep the agent focused.
  * **Result Injection:** Click "Add to context" on any file or output to feed it back into the next prompt.
* **Robust Architecture:**
  * Built on **Flask** (Backend) and **FastMCP** (Model Context Protocol).
  * Uses a local MCP server (`optics_mcp`) to expose file reading tools and validation schemas efficiently.

---

## ⚙️ Configuration

You can tune the behavior of every agent in `pipeline_context.json`.

| **Section**      | **Description**                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------- |
| **`models`**   | Select the specific LLMs for Thinker, Drafter, and Reviewer (must be OpenRouter IDs). |
| **`thinker`**  | System prompts and constraints for the physics planning stage.                        |
| **`drafter`**  | Rules for code generation (e.g., "No Markdown," "Use Numpy").                         |
| **`reviewer`** | Validation rules and strict JSON schema enforcement.                                  |
| **`llm`**      | Fine-tune temperature and token limits for each stage.                                |

**Example Model Config:**

**JSON**

```
"models": {
  "thinker_model": "google/gemini-flash-1.5",
  "drafter_model": "google/gemini-flash-1.5",
  "reviewer_model": "openai/gpt-4o"
}
```

---

## 📂 Project Structure

* **`server.py`** : The main Flask application. Handles the agent pipeline, OpenRouter calls, and code execution.
* **`optics_mcp/`** : The local Model Context Protocol server.
* `optics_server.py`: Defines resources (`ui-output-format`) and tools (`validate_json`) used by the LLM.
* **`static/`** : Frontend assets (HTML/JS/CSS).
* **`saved_json/`** : Where final designs are saved.
* **`tmp_runs/`** : Temporary sandbox directories for code execution.

---

## 🛠️ Troubleshooting

**"The agent is writing code but it's not appearing."**

* Check the console logs. The Drafter might be hitting a `tool_call` issue. Ensure your `server.py` has the extraction logic to handle "Agentic" model outputs.

**"The physics seems wrong."**

* Check the **Thinker's** output in the logs. If the blueprint is wrong, the code will be wrong. You can edit the Thinker's system prompt in `pipeline_context.json` to be stricter about specific physical laws.

**"Response Error 429/404"**

* Ensure your model IDs in `pipeline_context.json` are valid OpenRouter endpoints. Avoid `:free` endpoints for production use as they rate-limit frequently.
