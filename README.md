# AI Optics Agent: A Cyber-Physical System for Optical Experiment Automation

## Abstract

The AI Optics Agent is a specialized computational framework designed to automate the lifecycle of optical experimentation. By integrating Large Language Model (LLM) reasoning with a rigorous Cyber-Physical System (CPS) architecture, the system orchestrates the transition from theoretical design to physical implementation. The architecture enforces strict state management and sequential processing to ensure the generation of valid, physically realizable experimental parameters and robotic control sequences.

---

## System Architecture

The core functionality is governed by a finite state machine that transitions through four distinct operational stages. Each stage is managed by specialized algorithmic agents and pipelines to ensure data integrity and physical safety.

### 1. Feasibility Assessment Stage
*   **Module:** `stages/feasibility.py`
*   **Objective:** To evaluate the physical viability of the proposed experiment against defined constraints and available inventory.
*   **Mechanism:** The `FeasibilityAgent` analyzes the user's intent and the provided inventory list. It performs a semantic and physical cross-check to issue a binary determination (GO/NO-GO) regarding the experiment's safety and realizability.

### 2. Theoretical Design Stage
*   **Module:** `stages/design.py`
*   **Objective:** To generate a rigorous physical simulation and establish theoretical parameters.
*   **Pipeline:** `ArchitectPipeline`
    *   **Physics Reasoning Engine:** Determines the applicable physical regime (e.g., Geometric vs. Wave Optics) and identifies necessary mathematical constraints.
    *   **Simulation Generation:** Synthesizes executable Python code using scientific libraries (`numpy`, `scipy`) to model the optical system.
    *   **Validation:** A dedicated review process verifies the physical accuracy and syntactical correctness of the generated model.
*   **Output:** A validated `DesignState` object containing simulation results and optimized design parameters.

### 3. Construction Planning Stage
*   **Module:** `stages/construction.py`
*   **Objective:** To translate theoretical design parameters into a spatial layout compatible with physical laboratory constraints.
*   **Pipeline:** `ConstructionPipeline`
    *   **Mechanism:** The `ConstructorAgent` maps relative optical path lengths and component sequences to absolute coordinates ($x, y, \theta$) on the optical table frame.
*   **Output:** A `LabPlan` JSON structure defining the precise spatial configuration of all optical components.

### 4. Robotic Integration Stage
*   **Module:** `stages/robot.py`
*   **Objective:** To automate the physical assembly of the experiment using robotic manipulators.
*   **Pipeline:** `AssemblyPipeline`
    *   **Mechanism:** The `RoboticsEngineerAgent` ingests the `LabPlan` and generates a control script compliant with the specific robotic API (e.g., xArm SDK).
*   **Output:** An executable Python script (`robot_assembly.py`) enabling the robotic arm to place components according to the generated layout.

---

## Software Organization

The repository follows a modular architecture, separating agentic reasoning, core infrastructure, and interface logic.

```text
/
├── agents/             # Implementation of individual AI agents and their logic
├── config/             # Configuration files for system prompts and model parameters
├── core/               # Core infrastructure components
│   ├── llm.py          # Abstracted interface for LLM API interaction
│   ├── session.py      # Session state management and request routing
│   └── state.py        # Formal schema definitions for system state (Pydantic models)
├── knowledge/          # Contextual knowledge base and API specifications
├── optics_mcp/         # Local Model Context Protocol (MCP) server implementation
├── pipelines/          # Linear workflows coordinating multi-agent execution
├── stages/             # Finite State Machine logic implementation
├── static/             # Frontend application assets (HTML/JS/CSS)
└── server.py           # Flask backend application entry point
```

---

## Core Components

### The Server (`server.py`)
A lightweight Flask application serving as the interface layer. It manages HTTP endpoints for session initialization, real-time communication streams (Server-Sent Events), state transitions, and sandboxed code execution.

### Session Management (`core/session.py`)
The central controller of the application. The `Session` class persists conversation history, maintains the current `DesignState`, and routes execution to the appropriate `Stage` handler based on the current system state.

### User Interface (`static/`)
A Single Page Application (SPA) designed for real-time interaction. It visualizes the state machine's progress, renders simulation outputs (plots, code blocks), and provides controls for parameter verification and file management.

---

## Deployment

### Prerequisites
*   Python 3.10 or higher
*   Valid OpenRouter API credentials

### Installation Procedure

1.  **Repository Setup**
    Clone the repository to the local environment.

2.  **Dependency Installation**
    Execute the following command to install required packages:
    ```bash
    pip install -r requirements.txt
    ```

3.  **API Configuration**
    Create a file named `openrouter_api.txt` in the root directory and populate it with the API key.

### Execution

1.  **Initialize Server**
    ```bash
    python server.py
    ```

2.  **Access Interface**
    Navigate to `http://localhost:8001` via a web browser.

---

## Configuration and Extensibility

System behavior can be modified via configuration files located in the `config/` directory.

*   **Agent Configuration (`config/agents/*.json`)**: Defines the system prompts, roles, and operational constraints for each agent.
*   **Global Settings (`core/config.py`)**: Manages model selection and global system parameters.

### Development Workflow

To extend the system's capabilities:

1.  **Stage Implementation**: Define a new class in `stages/` implementing the `run()` method and register it within `core/session.py`.
2.  **Agent Logic**: Implement new agent classes in `agents/` and define their pipelines in `pipelines/`.
3.  **Interface Adaptation**: Update `static/app.js` to render the new stage's state and controls.
