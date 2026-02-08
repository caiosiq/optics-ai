# Project Roadmap

This document outlines the strategic plan for the evolution of the AI Optics Agent platform.

## Phase 1: Architecture Strengthening (Immediate)
Focus on stability, security, and developer experience.

*   **Configuration Management**:
    *   [ ] Migrate from `openrouter_api.txt` to `.env` using `python-dotenv`.
    *   [ ] Standardize configuration loading across `core/config.py` and `server.py`.
*   **Testing Infrastructure**:
    *   [ ] Initialize a `tests/` directory.
    *   [ ] Add `pytest` based unit tests for core logic (`core/state.py`, `core/session.py`).
    *   [ ] Add integration tests for the Flask endpoints.
*   **Code Quality**:
    *   [ ] Add type hinting (mypy) compliance across the codebase.
    *   [ ] Implement a linter (flake8 or ruff) CI check.

## Phase 2: Frontend Modernization (Mid-term)
Transition from vanilla JS to a scalable component framework to handle increasing UI complexity.

*   **Framework Migration**:
    *   [ ] Refactor `static/app.js` into a React or Vue.js application.
    *   [ ] Implement a build system (Vite) for better asset management.
*   **UI/UX Improvements**:
    *   [ ] Add proper error boundary handling.
    *   [ ] Improve the visualization of the optical table (Canvas/SVG interactive view).
    *   [ ] Add syntax highlighting for the generated Python code blocks.

## Phase 3: Backend Scalability & Performance (Long-term)
Prepare the system for multi-user support and complex concurrent simulations.

*   **Async Architecture**:
    *   [ ] Migrate from Flask to **FastAPI** to leverage native async/await support, improving performance for long-running agent tasks and SSE streams.
*   **Persistence**:
    *   [ ] Replace in-memory `SESSIONS` dictionary with a proper database (SQLite/PostgreSQL) or Redis cache.
    *   [ ] Implement persistent user accounts and saved project history.
*   **Execution Sandboxing**:
    *   [ ] Harden the `run_code` endpoint using Docker containers or a secure sandbox environment to prevent unsafe code execution.

## Phase 4: Expanded Capabilities (Future)
Broaden the scientific and physical scope of the agent.

*   **Feasibility**:
    *   [ ] Integrate real-time vendor APIs (Thorlabs, Newport) for stock checking and pricing.
*   **Robotics**:
    *   [ ] Abstract the robot control layer to support Universal Robots (UR), KUKA, and Dobot via a plugin system.
    *   [ ] Add computer vision feedback loop for calibration during assembly.
*   **Simulation**:
    *   [ ] Support more complex wave optics simulations (e.g., diffractive elements, non-linear optics).

---

## Contributing
To pick up a task from this roadmap:
1.  Create a branch `feature/task-name`.
2.  Implement the change.
3.  Add relevant tests.
4.  Submit a Pull Request.
