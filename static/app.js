// Global State
let conversationId = null
let selectedModel = 'google/gemini-3-pro-preview'
let drafterModel = 'google/gemini-3-pro-preview'

const messagesEl = document.getElementById('messages')
const inputEl = document.getElementById('input')
const sendBtn = document.getElementById('send')
const contextBar = document.getElementById('contextBar')
const warningBar = document.getElementById('warningBar')
const modelTag = document.getElementById('modelTag')
const landingOverlay = document.getElementById('landingOverlay')
const inventorySection = document.getElementById('inventorySection')
const inventoryInput = document.getElementById('inventoryInput')
const sidebar = document.getElementById('sidebar')
const checklistItems = document.getElementById('checklistItems')
const sidebarStatus = document.getElementById('sidebarStatus')
const designGoalTitle = document.getElementById('designGoalTitle')
const sidebarActions = document.getElementById('sidebarActions')

let currentGoal = null
let designState = null

// Toast Logic
function showToast(msg, type = 'info') {
    const container = document.getElementById('toastContainer') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = type === 'error' ? `<span>⚠️</span> ${msg}` : `<span>ℹ️</span> ${msg}`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function createToastContainer() {
    const div = document.createElement('div');
    div.id = 'toastContainer';
    div.className = 'toast-container';
    document.body.appendChild(div);
    return div;
}

window.app = {
  selectGoal: (goal) => {
    currentGoal = goal
    document.querySelector('.landing-options').style.display = 'none'
    inventorySection.style.display = 'block'
    document.querySelector('.landing-title').textContent = `Build: ${goal}`
  },
  
  selectCustomGoal: () => {
    const input = document.getElementById('customGoalInput')
    const val = input.value.trim()
    if (!val) return
    window.app.selectGoal(val)
  },

  cancelBuild: () => {
    currentGoal = null
    document.querySelector('.landing-options').style.display = 'grid'
    inventorySection.style.display = 'none'
    document.querySelector('.landing-title').textContent = 'What do you want to build today?'
  },

  startFreeChat: () => {
    landingOverlay.style.display = 'none'
    selectedModel = 'google/gemini-3-pro-preview'
    conversationId = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2))
    modelTag.textContent = 'reviewer: ' + selectedModel + ' • drafter: ' + (drafterModel || 'default')
  },

  confirmBuild: async () => {
    const inv = inventoryInput.value.trim()
    if (!inv) { showToast('Please list at least one item.', 'error'); return }
    
    const btn = document.querySelector('#inventorySection button:last-child')
    const originalText = btn.textContent
    btn.textContent = 'Analyzing Feasibility...'
    btn.disabled = true
    
    try {
      conversationId = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2))
      
      const r = await fetch('/init_design', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          goal: currentGoal,
          inventory: inv,
          model: 'google/gemini-3-pro-preview'
        })
      })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || 'Init failed')
      
      // Update Global State
      designState = j.state
      currentGoal = j.state.goal

      // Enter Design Mode
      window.app.enterDesignMode(j.state, j.message)

    } catch (e) {
      showToast('Error: ' + e.message, 'error')
      btn.textContent = originalText
      btn.disabled = false
    }
  },

  enterDesignMode: (state, initialMessage) => {
      // 1. Update UI Elements
      landingOverlay.style.opacity = '0'
      setTimeout(() => {
        landingOverlay.style.display = 'none'
        
        // Show Design View, Hide Construction
        document.getElementById('designView').style.display = 'flex'
        document.getElementById('constructionView').style.display = 'none'

        // Sidebar slide in
        sidebar.style.display = 'flex'
        sidebar.style.transform = 'translateX(-100%)'
        requestAnimationFrame(() => {
            sidebar.style.transform = 'translateX(0)'
        })

        designGoalTitle.textContent = state.goal
        document.querySelector('.sidebar-header .tag').textContent = 'Design Phase'
        
        // Update Progress Bar
        document.getElementById('progressContainer').style.display = 'flex'
        updateProgress('design')
        
        // Initial render of checklist
        updateChecklist(state)
        
        // Add agent's initial message if provided
        if (initialMessage) {
            appendBlock('agent', initialMessage)
        }
        
        // Set model tag
        selectedModel = 'google/gemini-3-pro-preview'
        modelTag.textContent = 'Design Mode • ' + selectedModel
      }, 500)
  },

  enterConstructionMode: (state) => {
      console.log("Entering construction mode", state)
      // 1. Hide Landing & Design
      landingOverlay.style.display = 'none'
      document.getElementById('designView').style.display = 'none'
      
      // 2. Show Construction View
      const cView = document.getElementById('constructionView')
      cView.style.display = 'flex'
      
      // 3. Update Progress Bar
      document.getElementById('progressContainer').style.display = 'flex'
      updateProgress('construction')
      
      // 4. Sidebar handling (Hidden in Construction)
      sidebar.style.display = 'none'
      
      // 5. Populate Construction Summary
      const summaryDiv = document.getElementById('constructionSummary')
      if (summaryDiv) {
          summaryDiv.innerHTML = ''
          
          // A. Setup Name
          const goalBlock = document.createElement('div')
          goalBlock.style.marginBottom = '20px'
          goalBlock.innerHTML = `
            <div style="color:rgba(255,255,255,0.5); font-size:12px; text-transform:uppercase; margin-bottom:4px;">Setup Name</div>
            <div style="color:#fff; font-size:18px; font-weight:600;">${state.goal}</div>
          `
          summaryDiv.appendChild(goalBlock)

          // B. Inventory
          const invBlock = document.createElement('div')
          invBlock.style.marginBottom = '24px'
          invBlock.innerHTML = `
            <div style="color:rgba(255,255,255,0.5); font-size:12px; text-transform:uppercase; margin-bottom:4px;">Lab Inventory</div>
            <div style="color:#ddd; font-size:14px; line-height:1.4; background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">${state.inventory}</div>
          `
          summaryDiv.appendChild(invBlock)

          // C. Parameters
          const renderSummarySection = (title, list) => {
              if (!list || list.length === 0) return
              
              const paramHeader = document.createElement('h4')
              paramHeader.textContent = title
              paramHeader.style.color = '#66fcf1'
              paramHeader.style.marginTop = '16px'
              paramHeader.style.marginBottom = '12px'
              paramHeader.style.borderBottom = '1px solid rgba(102, 252, 241, 0.3)'
              paramHeader.style.paddingBottom = '8px'
              summaryDiv.appendChild(paramHeader)

              if (title === "Design Parameters" && state.design_scheme) {
                  const schemeBlock = document.createElement('div')
                  schemeBlock.style.padding = '8px 12px'
                  schemeBlock.style.background = 'rgba(69, 162, 158, 0.1)'
                  schemeBlock.style.borderLeft = '3px solid #66fcf1'
                  schemeBlock.style.marginBottom = '12px'
                  schemeBlock.style.fontSize = '13px'
                  schemeBlock.style.color = '#e6f7f8'
                  schemeBlock.style.fontStyle = 'italic'
                  schemeBlock.textContent = state.design_scheme
                  summaryDiv.appendChild(schemeBlock)
              }

              list.forEach(p => {
                  const row = document.createElement('div')
                  row.style.display = 'flex'
                  row.style.justifyContent = 'space-between'
                  row.style.padding = '8px 0'
                  row.style.borderBottom = '1px solid rgba(102, 252, 241, 0.1)'
                  
                  const name = document.createElement('span')
                  name.textContent = p.name
                  name.style.color = '#fff'
                  name.style.fontSize = '14px'
                  
                  const val = document.createElement('span')
                  val.textContent = `${p.value} ${p.unit || ''}`
                  val.style.color = '#66fcf1'
                  val.style.fontWeight = 'bold'
                  val.style.fontSize = '14px'
                  
                  row.appendChild(name)
                  row.appendChild(val)
                  summaryDiv.appendChild(row)
              })
          }

          renderSummarySection("Component Properties", state.component_properties)
          renderSummarySection("Design Parameters", state.design_parameters || state.params)
      }
      
      // 6. Check for existing plan
      if (state.lab_plan && state.lab_plan.length > 0) {
          app.renderLabPlan(state.lab_plan, state.construction_thought)
      }
  },

  enterAssemblyMode: (state) => {
      // 1. Hide others
      landingOverlay.style.display = 'none'
      document.getElementById('designView').style.display = 'none'
      document.getElementById('constructionView').style.display = 'none'
      
      // 2. Show Assembly
      const aView = document.getElementById('assemblyView')
      if (aView) aView.style.display = 'flex'
      
      // 3. Update Progress
      updateProgress('assembly')
      
      // 4. Sidebar handling (Hidden)
      sidebar.style.display = 'none'

      // 5. Restore if exists
      if (state.robot_code) {
          app.renderRobotCode(state.robot_code)
      }

      // 6. Show loaded plan
      const planContainer = document.getElementById('assemblyPlanContainer')
      if (planContainer) {
          planContainer.innerHTML = ''
          if (state.lab_plan && state.lab_plan.length > 0) {
              app.renderPlanTable(state.lab_plan, planContainer)
          } else {
             planContainer.innerHTML = '<div style="color:#ff6b6b; font-size:14px;">No Lab Plan loaded.</div>'
          }
      }
  },

  generateRobotCode: async () => {
      const btn = document.getElementById('btnGenerateRobot')
      const loading = document.getElementById('assemblyLoading')
      const container = document.getElementById('robotCodeContainer')
      
      console.log("Starting robot code generation...");
      
      btn.disabled = true
      btn.textContent = 'Generating...'
      loading.style.display = 'flex' // flex to align loader
      loading.style.alignItems = 'center'
      container.style.display = 'none'
      
      try {
          const r = await fetch('/generate_robot_code', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ conversation_id: conversationId })
          })
          const j = await r.json()
          console.log("Robot code response:", j);
          
          if (!j.ok) throw new Error(j.error || 'Generation failed')
          
          if (!j.result.robot_code) {
              showToast("Warning: Generated code is empty", 'error');
          }

          designState.robot_code = j.result.robot_code
          app.renderRobotCode(j.result.robot_code)
          showToast("Robot code generated!", 'success')
          
      } catch (e) {
          console.error("Robot code generation error:", e);
          showToast("Error: " + e.message, 'error')
      } finally {
          btn.disabled = false
          btn.textContent = 'Regenerate Code'
          loading.style.display = 'none'
      }
  },

  renderRobotCode: (code) => {
      const container = document.getElementById('robotCodeContainer')
      const codeBlock = document.getElementById('robotCodeBlock')
      
      if (!container || !codeBlock) {
          console.error("Missing robot code container elements");
          return;
      }

      codeBlock.textContent = code || "# No code generated."
      container.style.display = 'flex'
      // Force layout update if needed
      container.style.opacity = '1'
  },

  downloadRobotCode: () => {
      if (!designState || !designState.robot_code) return
      const dataStr = "data:text/x-python;charset=utf-8," + encodeURIComponent(designState.robot_code);
      const downloadAnchorNode = document.createElement('a');
      downloadAnchorNode.setAttribute("href", dataStr);
      downloadAnchorNode.setAttribute("download", "robot_assembly.py");
      document.body.appendChild(downloadAnchorNode); 
      downloadAnchorNode.click();
      downloadAnchorNode.remove();
  },

  generateLabPlan: async () => {
      const btn = document.getElementById('btnGeneratePlan')
      const loading = document.getElementById('constructionLoading')
      const container = document.getElementById('labPlanContainer')
      
      btn.disabled = true
      btn.textContent = 'Generating...'
      loading.style.display = 'block'
      container.style.display = 'none'
      
      try {
          const r = await fetch('/generate_lab_plan', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ conversation_id: conversationId })
          })
          const j = await r.json()
          if (!j.ok) throw new Error(j.error || 'Generation failed')
          
          designState.lab_plan = j.result.lab_plan
          designState.construction_thought = j.result.thought_process
          
          app.renderLabPlan(j.result.lab_plan, j.result.thought_process)
          
      } catch (e) {
          showToast("Error: " + e.message, 'error')
      } finally {
          btn.disabled = false
          btn.textContent = 'Regenerate Lab Plan'
          loading.style.display = 'none'
      }
  },

  renderPlanTable: (plan, container) => {
      const table = document.createElement('table')
      table.className = 'preview'
      table.style.width = '100%'
      
      const thead = document.createElement('thead')
      thead.innerHTML = `
        <tr>
            <th style="text-align:left">ID</th>
            <th style="text-align:left">Type</th>
            <th style="text-align:right">X (cm)</th>
            <th style="text-align:right">Y (cm)</th>
            <th style="text-align:right">Angle (°)</th>
        </tr>
      `
      table.appendChild(thead)
      
      const tbody = document.createElement('tbody')
      plan.forEach(item => {
          const tr = document.createElement('tr')
          tr.innerHTML = `
            <td>${item.id}</td>
            <td>${item.type}</td>
            <td style="text-align:right; font-family:monospace; color:#66fcf1">${item.position.x}</td>
            <td style="text-align:right; font-family:monospace; color:#66fcf1">${item.position.y}</td>
            <td style="text-align:right; font-family:monospace;">${item.orientation}</td>
          `
          tbody.appendChild(tr)
      })
      table.appendChild(tbody)
      container.appendChild(table)
  },

  renderLabPlan: (plan, thought) => {
      const container = document.getElementById('labPlanContainer')
      const actions = document.getElementById('postPlanActions')
      container.innerHTML = ''
      container.style.display = 'block'
      actions.style.display = 'flex'
      
      if (thought) {
          const tDiv = document.createElement('div')
          tDiv.style.marginBottom = '20px'
          tDiv.style.color = '#ccc'
          tDiv.style.fontStyle = 'italic'
          tDiv.style.fontSize = '13px'
          tDiv.textContent = thought
          container.appendChild(tDiv)
      }
      
      app.renderPlanTable(plan, container)
  },

  downloadLabPlan: () => {
      if (!designState || !designState.lab_plan) return
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(designState.lab_plan, null, 2));
      const downloadAnchorNode = document.createElement('a');
      downloadAnchorNode.setAttribute("href", dataStr);
      downloadAnchorNode.setAttribute("download", "lab_plan.json");
      document.body.appendChild(downloadAnchorNode); 
      downloadAnchorNode.click();
      downloadAnchorNode.remove();
  },

  proceedToAssembly: async () => {
      // Use custom confirmation later, for now browser confirm is ok or skip
      // But user said: "I would like the notification to be in the UI not on the browser window"
      // So we should use a custom modal. For now, simple toast and proceed.
      // Or just proceed.
      
      try {
          const r = await fetch('/transition_stage', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ 
                  conversation_id: conversationId,
                  stage: 'ROBOT_ASSEMBLY'
              })
          })
          const j = await r.json()
          if (j.ok) {
              // Update state locally just in case
              designState.stage = 'ROBOT_ASSEMBLY'
              window.app.enterAssemblyMode(j.state || designState)
              showToast("Entered Robot Assembly Stage", 'success')
          }
      } catch (e) {
          showToast("Transition failed: " + e.message, 'error')
      }
  },

  downloadDesign: () => {
    if (!designState) return
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(designState, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", "design_" + (designState.goal || "optics").replace(/\s+/g, '_') + ".json");
    document.body.appendChild(downloadAnchorNode); 
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
  },

  proceedToConstruction: () => {
    if (!designState) return
    window.app.enterConstructionMode(designState)
  },

  handleFileUpload: (event, forcedStage = null) => {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);
        
        // 1. Check if it's a Lab Plan (Array) or Design State (Object)
        const isLabPlan = Array.isArray(json);
        
        // 2. Initialize State
        let newState = {};
        
        if (isLabPlan) {
            // It's a raw lab plan array
            newState = {
                goal: "Imported Lab Plan",
                inventory: "Unknown",
                lab_plan: json,
                stage: "ROBOT_ASSEMBLY",
                design_parameters: [],
                component_properties: []
            };
        } else {
            // It's a full Design State object
            const hasLegacy = json.params;
            const hasNew = json.component_properties || json.design_parameters;
            
            if (!json.goal || (!hasLegacy && !hasNew)) {
                showToast("Invalid design file format.", 'error');
                return;
            }
            newState = json;
        }

        designState = newState;
        conversationId = designState.conversation_id || (crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2)));
        
        // 3. Stage Logic
        if (forcedStage) {
             if (forcedStage === 'ROBOT_ASSEMBLY' && (!designState.lab_plan || designState.lab_plan.length === 0)) {
                 showToast("File missing Lab Plan for Assembly stage.", 'error');
                 return;
             }
             designState.stage = forcedStage;
        } else if (!designState.stage) {
             // Fallback auto-infer
             if (designState.lab_plan && designState.lab_plan.length > 0) {
                 designState.stage = "ROBOT_ASSEMBLY";
             } else {
                 const hasParams = (designState.design_parameters && designState.design_parameters.length > 0) || 
                                   (designState.params && designState.params.length > 0);
                 if (hasParams) {
                     designState.stage = "CONSTRUCTION";
                 }
             }
        }

        fetch('/load_session', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                conversation_id: conversationId,
                state: designState
            })
        }).then(r => r.json()).then(j => {
            if (j.ok) {
                // ROUTING LOGIC
                const stage = designState.stage || "DESIGN";
                
                if (stage === "CONSTRUCTION") {
                    window.app.enterConstructionMode(designState);
                } else if (stage === "ROBOT_ASSEMBLY") {
                    window.app.enterAssemblyMode(designState);
                } else {
                    // Default to Design
                    window.app.enterDesignMode(designState, "Session loaded.");
                }
            } else {
                showToast("Failed to restore session: " + j.error, 'error');
            }
        }).catch(e => showToast("Session restore error: " + e.message, 'error'));
        
      } catch (err) {
        showToast("Error parsing JSON: " + err.message, 'error');
      }
    };
    reader.readAsText(file);
  }
}

function updateProgress(stage) {
  ['design', 'construction', 'assembly'].forEach(s => {
    document.getElementById(`step-${s}`).classList.remove('active', 'completed');
  });
  ['line-1', 'line-2'].forEach(l => {
    document.getElementById(l).classList.remove('filled');
  });

  if (stage === 'design') {
    document.getElementById('step-design').classList.add('active');
  } else if (stage === 'construction') {
    document.getElementById('step-design').classList.add('completed');
    document.getElementById('line-1').classList.add('filled');
    document.getElementById('step-construction').classList.add('active');
  } else if (stage === 'assembly') {
    document.getElementById('step-design').classList.add('completed');
    document.getElementById('line-1').classList.add('filled');
    document.getElementById('step-construction').classList.add('completed');
    document.getElementById('line-2').classList.add('filled');
    document.getElementById('step-assembly').classList.add('active');
  }
}

// ----------------------------------------------------------------------
// UTILITY FUNCTIONS (RESTORED)
// ----------------------------------------------------------------------

function updateChecklist(state) {
    if (!checklistItems) return
    checklistItems.innerHTML = ''
    
    const params = state.design_parameters || state.params || []
    const props = state.component_properties || []
    
    // Helper to create item with INLINE INPUT
    const createItem = (label, val, type) => {
        const div = document.createElement('div')
        div.className = 'checklist-item' + (val !== null ? ' completed' : '')
        
        const checkbox = document.createElement('div')
        checkbox.className = 'checklist-icon'
        checkbox.innerHTML = val !== null ? '✓' : ''
        
        const content = document.createElement('div')
        content.className = 'checklist-content'
        
        const title = document.createElement('div')
        title.className = 'checklist-label'
        title.textContent = label
        
        const valueContainer = document.createElement('div')
        valueContainer.className = 'checklist-value-container'
        
        const input = document.createElement('input')
        input.type = 'text'
        input.className = 'checklist-input'
        input.value = val || ''
        input.placeholder = 'Value...'
        
        // Handle updates
        const commitChange = () => {
             const newValue = input.value.trim()
             // Only update if value actually changed from original (handle null vs empty string)
             const original = val === null ? '' : String(val)
             
             if (newValue !== original) {
                 if (newValue === '') {
                     // Maybe confirm delete? For now just update to empty/null
                 }
                 updateParam(label, newValue)
             }
        }

        input.onkeydown = (e) => {
            if (e.key === 'Enter') {
                input.blur() 
            }
        }
        
        input.onblur = commitChange
        
        valueContainer.appendChild(input)
        if (type === 'prop' || type === 'param') {
             // Add unit hint if we had it in schema? 
             // Currently we don't pass unit here easily, but state has it.
             // We could look it up.
             const itemObj = [...props, ...params].find(p => p.name === label)
             if (itemObj && itemObj.unit) {
                 const unitSpan = document.createElement('span')
                 unitSpan.style.fontSize = '10px'
                 unitSpan.style.color = '#888'
                 unitSpan.textContent = itemObj.unit
                 valueContainer.appendChild(unitSpan)
             }
        }
        
        content.appendChild(title)
        content.appendChild(valueContainer)
        
        div.appendChild(checkbox)
        div.appendChild(content)
        
        return div
    }

    // 1. Component Props
    if (props.length > 0) {
        const h = document.createElement('div')
        h.textContent = "COMPONENTS"
        h.style.fontSize = '10px'
        h.style.color = '#66fcf1'
        h.style.marginBottom = '4px'
        h.style.marginTop = '8px'
        h.style.fontWeight = '700'
        h.style.letterSpacing = '1px'
        checklistItems.appendChild(h)
        props.forEach(p => checklistItems.appendChild(createItem(p.name, p.value, 'prop')))
    }

    // 2. Design Params
    if (params.length > 0) {
        const h = document.createElement('div')
        h.textContent = "PARAMETERS"
        h.style.fontSize = '10px'
        h.style.color = '#66fcf1'
        h.style.marginBottom = '4px'
        h.style.marginTop = '8px'
        h.style.fontWeight = '700'
        h.style.letterSpacing = '1px'
        checklistItems.appendChild(h)
        params.forEach(p => checklistItems.appendChild(createItem(p.name, p.value, 'param')))
    }
    
    // Update status
    const total = props.length + params.length
    const filled = props.filter(p=>p.value).length + params.filter(p=>p.value).length
    sidebarStatus.textContent = filled === total ? "Ready for Construction" : `${filled}/${total} Parameters Set`
    
    // Show actions if complete
    if (filled === total && total > 0) {
        sidebarActions.style.display = 'flex'
    } else {
        sidebarActions.style.display = 'none'
    }
}

async function updateParam(name, value) {
    if (!conversationId) return
    try {
        const r = await fetch('/update_parameter', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                conversation_id: conversationId,
                name: name,
                value: value
            })
        })
        const j = await r.json()
        if (j.ok) {
            designState = j.state
            // We re-render checklist, but focus might be lost. 
            // Ideally we should update just the item, but full re-render is safer for sync.
            updateChecklist(designState)
            
            // Show toast instead of chat message?
            showToast(`Updated ${name}`, 'success')
            // appendBlock('system', `Updated ${name} to ${value}`) 
        } else {
            showToast("Update failed: " + j.error, 'error')
        }
    } catch(e) {
        console.error(e)
    }
}

function appendBlock(type, text, targetId = 'messages') {
    const container = document.getElementById(targetId)
    if (!container) return
    
    const div = document.createElement('div')
    div.className = `message ${type}`
    
    // Icon
    const icon = document.createElement('div')
    icon.className = 'icon'
    icon.textContent = type === 'user' ? 'U' : (type === 'system' ? 'S' : 'A')
    
    // Content
    const content = document.createElement('div')
    content.className = 'content'
    
    if (type === 'agent' || type === 'system') {
        // Markdown parsing (simple)
        let html = text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
            .replace(/\n/g, '<br>')
        content.innerHTML = html
    } else {
        content.textContent = text
    }
    
    div.appendChild(icon)
    div.appendChild(content)
    container.appendChild(div)
    container.scrollTop = container.scrollHeight
}

function showLoading(targetId = 'messages') {
    const container = document.getElementById(targetId)
    const div = document.createElement('div')
    div.className = 'message agent loading'
    div.innerHTML = `
        <div class="icon">A</div>
        <div class="content"><span class="loader"></span> Thinking...</div>
    `
    container.appendChild(div)
    container.scrollTop = container.scrollHeight
    return div
}

async function sendFlow(text, loadingEl, controller, startTime, targetId = 'messages') {
    if (!conversationId) {
        showToast("No active session", 'error')
        if (loadingEl) loadingEl.remove()
        return
    }

    try {
        const response = await fetch('/chat_flow', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversation_id: conversationId,
                message: text
            }),
            signal: controller.signal
        })

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let currentBlock = null

        while (true) {
            const { done, value } = await reader.read()
            if (done) break
            
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n\n')
            buffer = lines.pop()

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    const eventType = line.split('\n')[0].replace('event: ', '').trim()
                    const dataLine = line.split('\n')[1]
                    if (!dataLine) continue
                    
                    const dataStr = dataLine.replace('data: ', '')
                    let data = {}
                    try { data = JSON.parse(dataStr) } catch(e) {}

                    if (eventType === 'status') {
                        if (loadingEl) {
                            loadingEl.querySelector('.content').innerHTML = 
                                `<span class="loader"></span> ${data.message || 'Processing...'}`
                        }
                    } else if (eventType === 'state_update') {
                        if (data.state) {
                            designState = data.state
                            updateChecklist(designState)
                        }
                    } else if (eventType === 'review') {
                        if (loadingEl) loadingEl.remove()
                        
                        // Main Response
                        if (data.response && data.response.text) {
                            appendBlock('agent', data.response.text, targetId)
                        }
                        
                        // Code Block
                        if (data.response && data.response.code) {
                            const codeDiv = document.createElement('div')
                            codeDiv.className = 'message agent'
                            codeDiv.innerHTML = `
                                <div class="icon">C</div>
                                <div class="content">
                                    <pre><code>${data.response.code}</code></pre>
                                    <div class="controls" style="margin-top:8px">
                                        <button onclick="runCode(this)">Run Simulation</button>
                                    </div>
                                </div>
                            `
                            document.getElementById(targetId).appendChild(codeDiv)
                        }
                    } else if (eventType === 'error') {
                        if (loadingEl) loadingEl.remove()
                        showToast(data.error || 'Unknown error', 'error')
                        // appendBlock('error', data.error || 'Unknown error', targetId)
                    }
                }
            }
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            if (loadingEl) loadingEl.remove()
            showToast(e.message, 'error')
        }
    }
}

// Code Execution
async function runCode(btn) {
    const pre = btn.parentElement.parentElement.querySelector('pre code')
    const code = pre.textContent
    
    btn.textContent = "Running..."
    btn.disabled = true
    
    try {
        const r = await fetch('/run_code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        })
        const j = await r.json()
        
        const resDiv = document.createElement('div')
        resDiv.className = 'message system'
        resDiv.innerHTML = `<div class="icon">R</div><div class="content"><pre>${j.output || 'No output'}</pre></div>`
        
        if (j.images) {
            j.images.forEach(b64 => {
                const img = document.createElement('img')
                img.src = 'data:image/png;base64,' + b64
                img.style.maxWidth = '100%'
                img.style.marginTop = '10px'
                img.style.borderRadius = '4px'
                resDiv.querySelector('.content').appendChild(img)
            })
        }
        
        btn.parentElement.parentElement.parentElement.after(resDiv)
        
    } catch(e) {
        showToast("Run failed: " + e.message, 'error')
    } finally {
        btn.textContent = "Run Simulation"
        btn.disabled = false
    }
}

// Chat Listeners
sendBtn.addEventListener('click', () => {
    const text = inputEl.value.trim()
    if (!text) return
    
    appendBlock('user', text)
    inputEl.value = ''
    
    const loading = showLoading()
    const ctrl = new AbortController()
    sendFlow(text, loading, ctrl, Date.now())
})

inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        sendBtn.click()
    }
})

// Initialize
// app.startFreeChat()
