
const messagesEl = document.getElementById('messages')
const inputEl = document.getElementById('input')
const sendBtn = document.getElementById('send')
const testBtn = document.getElementById('test')
const modelTag = document.getElementById('modelTag')
let selectedModel = 'google/gemini-3-pro-preview'
let conversationId = null
let drafterModel = null
let pendingDraftCode = null
let pendingDraftRaw = null
const contextBarEl = document.getElementById('contextBar')
let contextAdds = []
const warningBarEl = document.getElementById('warningBar')
const warnMinutes = 3

// --- Landing & State Logic ---
const landingOverlay = document.getElementById('landingOverlay')
const inventorySection = document.getElementById('inventorySection')
const inventoryInput = document.getElementById('inventoryInput')
const sidebar = document.getElementById('sidebar')
const checklistItems = document.getElementById('checklistItems')
const sidebarStatus = document.getElementById('sidebarStatus')
const designGoalTitle = document.getElementById('designGoalTitle')

let currentGoal = null
let designState = null

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
    if (!inv) { alert('Please list at least one item.'); return }
    
    // Show loading
    const btn = document.querySelector('#inventorySection button:last-child')
    const originalText = btn.textContent
    btn.textContent = 'Analyzing Feasibility...'
    btn.disabled = true
    
    try {
      // Ensure conversation ID exists
      conversationId = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2))
      
      const r = await fetch('/init_design', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          goal: currentGoal,
          inventory: inv,
          model: 'google/gemini-3-pro-preview' // Default for planning
        })
      })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || 'Init failed')
      
      // Setup UI for Design Mode
      // Animate Landing Away
      landingOverlay.style.opacity = '0'
      setTimeout(() => {
        landingOverlay.style.display = 'none'
        
        // Sidebar slide in
        sidebar.style.display = 'flex'
        sidebar.style.transform = 'translateX(-100%)'
        requestAnimationFrame(() => {
            sidebar.style.transform = 'translateX(0)'
        })

        designGoalTitle.textContent = currentGoal
        
        // Initial render of checklist
        updateChecklist(j.state)
        
        // Add agent's initial feasibility report to chat
        appendBlock('agent', j.message)
        
        // Set model (skip modal)
        selectedModel = 'google/gemini-3-pro-preview'
        modelTag.textContent = 'Design Mode • ' + selectedModel
      }, 500)

    } catch (e) {
      alert('Error: ' + e.message)
      btn.textContent = originalText
      btn.disabled = false
    }
  },

  enterConstructionMode: (state) => {
      console.log("Entering construction mode", state)
      // 1. Hide Landing
      landingOverlay.style.display = 'none'
      
      // 2. Hide Design View, Show Construction View
      document.getElementById('designView').style.display = 'none'
      const cView = document.getElementById('constructionView')
      cView.style.display = 'flex'
      
      // 3. Hide Sidebar (User requested removal in 3rd stage)
      sidebar.style.display = 'none'
      
      // 4. Update Sidebar Header (Not visible, but keeping state consistent)
      designGoalTitle.textContent = state.goal
      document.querySelector('.sidebar-header .tag').textContent = 'Construction Phase'
      
      // 5. Ensure actions are hidden
      sidebarActions.style.display = 'none'
      sidebarStatus.textContent = "Design Finalized. Ready for build."

      // 6. Populate Construction Summary
      const summaryDiv = document.getElementById('constructionSummary')
      if (summaryDiv) {
          summaryDiv.innerHTML = ''
          
          // A. Setup Name (Goal)
          const goalBlock = document.createElement('div')
          goalBlock.style.marginBottom = '20px'
          goalBlock.innerHTML = `
            <div style="color:rgba(255,255,255,0.5); font-size:12px; text-transform:uppercase; margin-bottom:4px;">Setup Name</div>
            <div style="color:#fff; font-size:18px; font-weight:600;">${state.goal}</div>
          `
          summaryDiv.appendChild(goalBlock)

          // B. Inventory (Lab Description)
          const invBlock = document.createElement('div')
          invBlock.style.marginBottom = '24px'
          invBlock.innerHTML = `
            <div style="color:rgba(255,255,255,0.5); font-size:12px; text-transform:uppercase; margin-bottom:4px;">Lab Inventory</div>
            <div style="color:#ddd; font-size:14px; line-height:1.4; background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">${state.inventory}</div>
          `
          summaryDiv.appendChild(invBlock)

          // C. Parameters Header
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
      
      // 7. Initialize Construction Chat Agent (if not already)
      const cMessages = document.getElementById('constructionMessages')
      if (cMessages && cMessages.innerHTML === '') {
          appendBlock('agent', "I am ready to help you build this. What parts do you have ready?", 'constructionMessages')
      }
  },

  sendConstruction: async () => {
      const inp = document.getElementById('constructionInput')
      const val = inp.value.trim()
      if (!val) return
      
      appendBlock('user', val, 'constructionMessages')
      inp.value = ''
      
      const loading = showLoading('constructionMessages')
      const ctrl = new AbortController()
      const startTime = Date.now()
      
      try {
          await sendFlow(val, loading, ctrl, startTime, 'constructionMessages')
      } catch(e) {
          if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
          appendBlock('error', String(e), 'constructionMessages')
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

  handleFileUpload: (event) => {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);
        if (!json.goal || !json.params) {
            alert("Invalid design file format.");
            return;
        }
        designState = json;
        // If conversation_id is missing, generate one
        conversationId = json.conversation_id || (crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2)));
        
        window.app.enterConstructionMode(designState);
        
      } catch (err) {
        alert("Error parsing JSON: " + err.message);
      }
    };
    reader.readAsText(file);
  }
}

function updateProgress(stage) {
  // Reset all
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

function updateChecklist(state) {
  if (!state) return
  designState = state
  checklistItems.innerHTML = ''
  
  // Calculate progress
  // We now have two lists: component_properties and design_parameters
  // Fallback for legacy state
  const comps = state.component_properties || []
  const params = state.design_parameters || state.params || []
  
  const total = comps.length + params.length
  const filled = comps.filter(p => p.value !== null).length + params.filter(p => p.value !== null).length
  sidebarStatus.textContent = `${filled}/${total} Fields Defined`
  
  // Check Completion
  if (filled === total && total > 0) {
      sidebarActions.style.display = 'flex'
  } else {
      sidebarActions.style.display = 'none'
  }

  // Helper to render a section
  const renderSection = (title, list, type) => {
      if (list.length === 0) return
      
      const header = document.createElement('div')
      header.className = 'checklist-header'
      header.textContent = title
      header.style.color = '#8fb7b9'
      header.style.fontSize = '11px'
      header.style.textTransform = 'uppercase'
      header.style.letterSpacing = '1px'
      header.style.marginTop = '16px'
      header.style.marginBottom = '8px'
      header.style.paddingLeft = '4px'
      checklistItems.appendChild(header)

      list.forEach(p => {
        const item = document.createElement('div')
        const isFilled = p.value !== null
        item.className = `checklist-item ${isFilled ? 'filled' : 'missing'}`
        
        const icon = document.createElement('div')
        icon.className = 'checklist-icon'
        icon.textContent = isFilled ? '✓' : '!'
        
        const content = document.createElement('div')
        content.className = 'checklist-content'
        
        const label = document.createElement('div')
        label.className = 'checklist-label'
        label.textContent = p.name
        label.title = p.description
        
        // Make value editable
        const valContainer = document.createElement('div')
        valContainer.className = 'checklist-value-container'
        
        if (isFilled) {
            // Editable Input
            const input = document.createElement('input')
            input.type = 'text'
            input.className = 'checklist-input'
            input.value = p.value
            
            const unit = document.createElement('span')
            unit.className = 'checklist-unit'
            unit.textContent = p.unit || ''

            // Save on blur or enter
            const save = async () => {
                const newVal = input.value.trim()
                if (newVal == p.value) return // No change
                
                try {
                    input.style.opacity = '0.5'
                    const r = await fetch('/update_parameter', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            conversation_id: conversationId,
                            name: p.name,
                            value: isNaN(Number(newVal)) ? newVal : Number(newVal)
                        })
                    })
                    const j = await r.json()
                    if (j.ok) {
                        // Update local state and re-render if needed, or just let the input be
                        // p.value = j.state.params.find(x => x.name === p.name).value
                        input.style.opacity = '1'
                        updateChecklist(j.state) // Refresh to ensure consistency
                    } else {
                        alert('Update failed: ' + j.error)
                        input.value = p.value
                        input.style.opacity = '1'
                    }
                } catch (e) {
                    alert('Update failed: ' + e.message)
                    input.value = p.value
                    input.style.opacity = '1'
                }
            }

            input.onblur = save
            input.onkeydown = (e) => { if (e.key === 'Enter') { input.blur() } }

            valContainer.appendChild(input)
            valContainer.appendChild(unit)

            // Reset/Delete Button
            const resetBtn = document.createElement('button')
            resetBtn.textContent = '✕'
            resetBtn.className = 'btn-ghost'
            resetBtn.style.padding = '0 4px'
            resetBtn.style.fontSize = '12px'
            resetBtn.style.marginLeft = '4px'
            resetBtn.title = 'Clear value'
            resetBtn.onclick = async () => {
                if (!confirm(`Clear value for ${p.name}?`)) return
                
                try {
                    const r = await fetch('/update_parameter', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            conversation_id: conversationId,
                            name: p.name,
                            value: null // Send null to clear
                        })
                    })
                    const j = await r.json()
                    if (j.ok) {
                        updateChecklist(j.state)
                    } else {
                        alert('Update failed: ' + j.error)
                    }
                } catch (e) {
                    alert('Update failed: ' + e.message)
                }
            }
            valContainer.appendChild(resetBtn)

        } else {
            // Missing (also editable to set it)
            const input = document.createElement('input')
            input.type = 'text'
            input.className = 'checklist-input missing-input'
            input.placeholder = 'Value?'
            
            const save = async () => {
                const newVal = input.value.trim()
                if (!newVal) return
                
                try {
                    input.style.opacity = '0.5'
                    const r = await fetch('/update_parameter', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            conversation_id: conversationId,
                            name: p.name,
                            value: isNaN(Number(newVal)) ? newVal : Number(newVal)
                        })
                    })
                    const j = await r.json()
                    if (j.ok) {
                        updateChecklist(j.state)
                    } else {
                        alert('Update failed: ' + j.error)
                        input.style.opacity = '1'
                    }
                } catch (e) {
                    alert('Update failed: ' + e.message)
                    input.style.opacity = '1'
                }
            }

            input.onblur = save
            input.onkeydown = (e) => { if (e.key === 'Enter') { input.blur() } }
            
            valContainer.appendChild(input)
        }
        
        content.appendChild(label)
        content.appendChild(valContainer)
        item.appendChild(icon)
        item.appendChild(content)
        checklistItems.appendChild(item)
      })
  }

  // Render Design Scheme (Plan)
  if (state.design_scheme) {
      const schemeHeader = document.createElement('div')
      schemeHeader.className = 'checklist-header'
      schemeHeader.textContent = 'Design Plan'
      checklistItems.appendChild(schemeHeader)
      
      const schemeDiv = document.createElement('div')
      schemeDiv.style.padding = '8px 12px'
      schemeDiv.style.background = 'rgba(69, 162, 158, 0.1)'
      schemeDiv.style.borderLeft = '3px solid #66fcf1'
      schemeDiv.style.marginBottom = '12px'
      schemeDiv.style.fontSize = '12px'
      schemeDiv.style.color = '#e6f7f8'
      schemeDiv.style.fontStyle = 'italic'
      schemeDiv.style.lineHeight = '1.4'
      schemeDiv.textContent = state.design_scheme
      checklistItems.appendChild(schemeDiv)
  }

  renderSection("Component Properties", comps, 'component')
  renderSection("Design Parameters", params, 'design')
}

// --- End Landing Logic ---

function appendBlock(label, content, targetId = 'messages') {
  const targetEl = document.getElementById(targetId) || messagesEl
  const wrap = document.createElement('div')
  const isUser = label === 'user'
  wrap.className = `bubble ${isUser ? 'bubble-user' : 'bubble-agent'}`
  const tag = document.createElement('div')
  tag.className = isUser ? 'tag tag-large' : 'tag'
  tag.textContent = isUser ? 'User' : label
  wrap.appendChild(tag)
  const c = document.createElement('div')
  // Handle markdown-like bolding removal
  c.textContent = content.replace(/\*\*/g, '')
  wrap.appendChild(c)
  targetEl.appendChild(wrap)
  targetEl.scrollTop = targetEl.scrollHeight
}

/* removed legacy appendCode/appendJson; unified rendering via renderLLMOutput + appendCodeIn/appendJsonIn */

function renderResponse(r) {
  renderLLMOutput(r.response || {}, r.metrics || null)
}

sendBtn.onclick = async () => {
  const v = inputEl.value.trim()
  if (!v) return
  if (!selectedModel) { 
      // If we are in design mode but somehow model is unset, set default
      selectedModel = 'google/gemini-3-pro-preview'
  }
  
  appendBlock('user', v)
  inputEl.value = ''
  const loading = showLoading()
  const ctrl = new AbortController()
  const warnTimer = setTimeout(() => showWarn(ctrl), warnMinutes * 60 * 1000)
  
  // Start timing
  const startTime = Date.now()
  
  try {
    // If in Design Mode, use the special endpoint or flow
    // Actually we can reuse chat_flow but we need to tell the backend to check for params
    // We will send the current designState context if needed, but backend has session store.
    
    await sendFlow(v, loading, ctrl, startTime)
    
  } catch (e) {
    if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
    hideWarn()
    appendBlock('error', String(e || 'request failed'))
  } finally {
    clearTimeout(warnTimer)
  }
}

testBtn.onclick = async () => {
  if (!selectedModel) selectedModel = 'google/gemini-3-pro-preview'
  const loading = showLoading()
  const ctrl = new AbortController()
  try {
    const r = await fetch('/test_response', { signal: ctrl.signal })
    const ct = r.headers.get('Content-Type') || ''
    const j = ct.includes('application/json') ? await r.json() : { ok: false, error: (await r.text()) }
    if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
    if (!j.ok) { appendBlock('error', j.error || 'error'); if (j.raw_message) appendDebug('raw_message', j.raw_message); if (j.raw_response) appendDebug('raw_response', j.raw_response); return }
    renderResponse(j)
  } catch (e) {
    if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
    appendBlock('error', String(e || 'request failed'))
  }
}

function showLoading() {
  const wrap = document.createElement('div')
  wrap.className = 'bubble bubble-agent'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = 'thinking'
  wrap.appendChild(tag)
  const row = document.createElement('div')
  row.className = 'row'
  const spin = document.createElement('div')
  spin.className = 'loader'
  const txt = document.createElement('div')
  txt.textContent = 'Processing request...'
  row.appendChild(spin)
  row.appendChild(txt)
  wrap.appendChild(row)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
  return wrap
}

async function displayFile(path, container) {
  const ext = (path.split('.').pop() || '').toLowerCase()
  const name = basename(path)
  if (['png','jpg','jpeg','gif','webp'].includes(ext)) {
    const img = document.createElement('img')
    img.src = '/download?path=' + encodeURIComponent(path)
    img.style.maxWidth = '100%'
    img.style.borderRadius = '8px'
    img.style.border = '1px solid #2a3b45'
    img.style.marginTop = '8px'
    container.appendChild(img)
    return
  }
  try {
    const r = await fetch('/download?path=' + encodeURIComponent(path))
    const type = r.headers.get('Content-Type') || ''
    if (ext === 'csv') {
      const text = await r.text()
      const table = document.createElement('table')
      table.className = 'preview'
      const lines = text.split(/\r?\n/).filter(Boolean).slice(0, 20)
      lines.forEach((line,i) => {
        const tr = document.createElement('tr')
        line.split(',').forEach(cell => {
          const td = document.createElement(i===0 ? 'th' : 'td')
          td.textContent = cell
          tr.appendChild(td)
        })
        table.appendChild(tr)
      })
      container.appendChild(table)
      const link = document.createElement('a')
      link.href = '/download?path=' + encodeURIComponent(path)
      link.textContent = 'Open ' + name
      link.target = '_blank'
      container.appendChild(link)
      return
    }
    if (ext === 'json' || type.includes('application/json')) {
      const obj = await r.json()
      const pre = document.createElement('pre')
      pre.className = 'code'
      pre.textContent = JSON.stringify(obj, null, 2)
      container.appendChild(pre)
      const link = document.createElement('a')
      link.href = '/download?path=' + encodeURIComponent(path)
      link.textContent = 'Open ' + name
      link.target = '_blank'
      container.appendChild(link)
      return
    }
    const text = await r.text()
    const pre = document.createElement('pre')
    pre.className = ext === 'txt' ? 'textdoc' : 'code'
    pre.textContent = text
    container.appendChild(pre)
    const link = document.createElement('a')
    link.href = '/download?path=' + encodeURIComponent(path)
    link.textContent = 'Open ' + name
    link.target = '_blank'
    container.appendChild(link)
  } catch (e) {
    const row = document.createElement('div')
    row.className = 'row'
    const a = document.createElement('a')
    a.href = '/download?path=' + encodeURIComponent(path)
    a.textContent = 'Open ' + basename(path)
    a.target = '_blank'
    row.appendChild(a)
    container.appendChild(row)
  }
}

function appendDebug(label, data) {
  const wrap = document.createElement('div')
  wrap.className = 'bubble bubble-agent'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = label
  wrap.appendChild(tag)
  const pre = document.createElement('pre')
  pre.className = 'code'
  try {
    pre.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  } catch {
    pre.textContent = String(data)
  }
  wrap.appendChild(pre)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
}

function renderLLMOutput(o, metrics, draftCode, draftRaw) {
  const wrap = document.createElement('div')
  wrap.className = 'bubble bubble-agent'
  const head = document.createElement('div')
  head.className = 'output-head'
  const tag = document.createElement('div')
  tag.className = 'tag tag-large'
  tag.textContent = 'LLM Output'
  head.appendChild(tag)
  const actions = document.createElement('div')
  actions.className = 'output-actions'
  const summary = document.createElement('div')
  if (metrics) {
    const prep = metrics.prep_ms ?? 0
    const llm = metrics.llm_ms ?? (metrics.reviewer_ms ?? 0)
    const post = metrics.post_ms ?? 0
    const tries = metrics.retries ?? 1
    summary.className = 'muted'
    const conf = (typeof metrics.confidence === 'number') ? ` • confidence ${(metrics.confidence*100).toFixed(0)}%` : ''
    const total = metrics.total_ms ?? (prep + llm + post)
    const thinker = metrics.thinker_ms ?? 0
    const drafter = metrics.drafter_ms ?? 0
    const reviewer = metrics.reviewer_ms ?? llm
    let parts = [`total ${total}ms`]
    if (thinker) parts.push(`thinker ${thinker}ms`)
    if (drafter) parts.push(`drafter ${drafter}ms`)
    if (reviewer) parts.push(`reviewer ${reviewer}ms`)
    parts.push(`prep ${prep}ms`, `llm ${llm}ms`, `post ${post}ms`, `attempts ${tries}`)
    summary.textContent = `timing: ${parts.join(' • ')}${conf}`
    summary.style.display = 'none'
  }
  const btn = document.createElement('button')
  btn.textContent = 'Show Timing'
  const pre = document.createElement('pre')
  pre.className = 'code'
  pre.style.display = 'none'
  pre.textContent = metrics ? JSON.stringify(metrics, null, 2) : '{}'
  btn.onclick = () => {
    const show = pre.style.display === 'none'
    pre.style.display = show ? 'block' : 'none'
    if (summary) summary.style.display = show ? 'block' : 'none'
    btn.textContent = show ? 'Hide Timing' : 'Show Timing'
  }
  actions.appendChild(summary)
  actions.appendChild(btn)
  head.appendChild(actions)
  wrap.appendChild(head)
  
  // Render Text parts
  if (o.text) {
      // Split text by Physics Analysis or Code Analysis header if present
      const parts = o.text.split(/(\*\*(?:Physics Analysis|Code Analysis).*?\*\*)/)
      
      let hiding = false
      parts.forEach(part => {
          if (!part.trim()) return
          
          if (part.startsWith('**Code Analysis')) {
              hiding = true
              return
          }

          if (part.startsWith('**Physics Analysis')) {
              hiding = false
              // This is the header/separator
              const div = document.createElement('div')
              div.className = 'physics-separator'
              
              const icon = document.createElement('span')
              icon.className = 'physics-icon'
              icon.textContent = '⚡'
              
              const txt = document.createElement('span')
              txt.textContent = part.replace(/\*\*/g, '')
              
              div.appendChild(icon)
              div.appendChild(txt)
              wrap.appendChild(div)
              return
          }
          
          if (hiding) return

          // Regular text block - remove bold markers
          appendTextIn(wrap, 'text', part.replace(/\*\*/g, ''))
      })
  }
  
  if (o.code) appendCodeIn(wrap, o.code, o.code_meta, draftCode, draftRaw)
  if (o.json_file) appendJsonIn(wrap, o.json_file)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
}

async function sendFlow(v, loading, ctrl, startTime) {
  try {
    const r = await fetch('/chat_flow', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: v, conversation_id: conversationId, drafter_model: drafterModel }), signal: ctrl.signal })
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const lines = chunk.split('\n')
        let ev = 'message'
        let data = ''
        for (const ln of lines) {
          if (ln.startsWith('event:')) ev = ln.slice(6).trim()
          if (ln.startsWith('data:')) data = ln.slice(5).trim()
        }
        if (!data) continue
        try {
          const payload = JSON.parse(data)
          if (ev === 'draft') {
            pendingDraftCode = payload.code || ''
            pendingDraftRaw = payload.raw || ''
          } else if (ev === 'review') {
            // Calculate total time
            const totalMs = Date.now() - startTime
            if (!payload.metrics) payload.metrics = {}
            payload.metrics.total_ms = totalMs
            
            renderLLMOutput(payload.response || {}, payload.metrics || null, pendingDraftCode, pendingDraftRaw)
            pendingDraftCode = null
            pendingDraftRaw = null
          } else if (ev === 'error') {
            appendBlock('error', payload.error || 'error')
          } else if (ev === 'state_update') {
            // New event type for state updates
            updateChecklist(payload.state)
          } else if (ev === 'status') {
             // Optional: Update loading bubble text
             if (loading) {
                 loading.querySelector('.row div:last-child').textContent = payload.message
             }
          }
        } catch {}
      }
    }
  } finally {
    if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
    hideWarn()
    if (contextBarEl) { contextAdds = []; renderContextBar() }
  }
}

function appendTextIn(container, label, content) {
  const blk = document.createElement('div')
  blk.className = 'block'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = label
  blk.appendChild(tag)
  const c = document.createElement('div')
  c.textContent = content
  blk.appendChild(c)
  container.appendChild(blk)
}

function appendCodeIn(container, code, meta, draftCode, draftRaw) {
  const blk = document.createElement('div')
  blk.className = 'block'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = 'code'
  blk.appendChild(tag)
  const tools = document.createElement('div')
  tools.className = 'code-tools'
  blk.appendChild(tools)
  if (draftCode && draftCode.trim()) {
    const toggle = document.createElement('button')
    toggle.textContent = 'Show Drafter Code'
    toggle.className = 'btn-sm btn-ghost btn-pill'
    const dpre = document.createElement('pre')
    dpre.className = 'code'
    dpre.style.display = 'none'
    dpre.textContent = draftCode
    toggle.onclick = () => {
      const show = dpre.style.display === 'none'
      dpre.style.display = show ? 'block' : 'none'
      toggle.textContent = show ? 'Hide Drafter Code' : 'Show Drafter Code'
    }
    tools.appendChild(toggle)
    blk.appendChild(dpre)
  }
  if (draftRaw && String(draftRaw).trim()) {
    const rtoggle = document.createElement('button')
    rtoggle.textContent = 'Show Draft Raw Reply'
    rtoggle.className = 'btn-sm btn-ghost btn-pill'
    const rpre = document.createElement('pre')
    rpre.className = 'code'
    rpre.style.display = 'none'
    rpre.textContent = typeof draftRaw === 'string' ? draftRaw : JSON.stringify(draftRaw, null, 2)
    rtoggle.onclick = () => {
      const show = rpre.style.display === 'none'
      rpre.style.display = show ? 'block' : 'none'
      rtoggle.textContent = show ? 'Hide Draft Raw Reply' : 'Show Draft Raw Reply'
    }
    tools.appendChild(rtoggle)
    blk.appendChild(rpre)
  }
  const codeBlock = renderCodeBlock(code)
  let editMode = false
  const editBtn = document.createElement('button')
  editBtn.textContent = 'Edit Code'
  editBtn.className = 'btn-sm btn-ghost btn-pill'
  const addBtn = document.createElement('button')
  addBtn.textContent = 'Add to context'
  addBtn.className = 'btn-sm btn-ghost btn-pill'
  tools.appendChild(editBtn)
  tools.appendChild(addBtn)
  editBtn.onclick = () => {
    editMode = !editMode
    codeBlock.querySelectorAll('.code-txt').forEach(el => { el.contentEditable = editMode ? 'true' : 'false' })
    editBtn.textContent = editMode ? 'Done Editing' : 'Edit Code'
  }
  addBtn.onclick = () => {
    const current = getCodeFromBlock(codeBlock) || String(code || '')
    contextAdds.push({ type: 'output', text: current })
    if (contextBarEl) renderContextBar()
  }
  blk.appendChild(codeBlock)
  const row = document.createElement('div')
  row.className = 'row'
  const run = document.createElement('button')
  run.textContent = 'Run Code'
  run.className = 'btn-sm btn-pill'
  const out = document.createElement('div')
  out.className = 'small'
  out.style.whiteSpace = 'pre-wrap'
  out.style.fontFamily = 'Consolas, monospace'
  run.onclick = async () => {
    out.textContent = 'Running...'
    const current = getCodeFromBlock(codeBlock) || String(code || '')
    const r = await fetch('/run_code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: current, code_meta: meta || null }) })
    const j = await r.json()
    if (j.ok) {
      out.textContent = (j.output || '[no output]')
    } else {
      const ln = j.error_user_line ?? j.error_line
      const kind = j.error_type || 'Error'
      const msg = j.error || 'execution failed'
      out.textContent = `Line ${ln ?? '?'}: ${kind} — ${msg}`
      const errPre = document.createElement('pre')
      errPre.className = 'code'
      errPre.textContent = (j.output || '')
      blk.appendChild(errPre)
    }
    if (j.ok && (j.output || '').trim()) {
      const addBtn = document.createElement('button')
      addBtn.textContent = 'Add output to context'
      addBtn.onclick = () => { contextAdds.push({ type: 'output', text: j.output }); if (contextBarEl) renderContextBar() }
      row.appendChild(addBtn)
    }
    if (j.images && j.images.length) {
      j.images.forEach(b64 => {
        const img = document.createElement('img')
        img.src = 'data:image/png;base64,' + b64
        img.style.maxWidth = '100%'
        img.style.borderRadius = '8px'
        img.style.border = '1px solid #2a3b45'
        img.style.marginTop = '8px'
        blk.appendChild(img)
      })
    }
    if (j.files && j.files.length) {
      const filesRow = document.createElement('div')
      filesRow.className = 'row'
      const toggle = document.createElement('button')
      toggle.textContent = 'Show Created Files'
      filesRow.appendChild(toggle)
      blk.appendChild(filesRow)
      const filesWrap = document.createElement('div')
      filesWrap.style.display = 'none'
      let loaded = false
      toggle.onclick = async () => {
        const show = filesWrap.style.display === 'none'
        filesWrap.style.display = show ? 'block' : 'none'
        if (show && !loaded) {
          loaded = true
          j.files.forEach(path => {
            displayFile(path, filesWrap)
            const add = document.createElement('button')
            add.textContent = 'Add ' + basename(path) + ' to context'
            add.onclick = async () => {
              try {
                const rr = await fetch('/download?path=' + encodeURIComponent(path))
                let snippet = ''
                const ct = rr.headers.get('Content-Type') || ''
                if (ct.includes('application/json')) {
                  const obj = await rr.json()
                  snippet = JSON.stringify(obj, null, 2)
                } else {
                  snippet = await rr.text()
                }
                contextAdds.push({ type: 'file', name: basename(path), text: snippet })
                if (contextBarEl) renderContextBar()
              } catch (e) {}
            }
            filesWrap.appendChild(add)
          })
        }
      }
      blk.appendChild(filesWrap)
    }
  }
  row.appendChild(run)
  row.appendChild(out)
  blk.appendChild(row)
  container.appendChild(blk)
}

function appendJsonIn(container, obj) {
  const blk = document.createElement('div')
  blk.className = 'block'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = 'json_file'
  blk.appendChild(tag)
  const pre = document.createElement('pre')
  pre.className = 'code'
  pre.textContent = JSON.stringify(obj, null, 2)
  blk.appendChild(pre)
  const row = document.createElement('div')
  row.className = 'row'
  const save = document.createElement('button')
  save.textContent = 'Save JSON'
  const note = document.createElement('div')
  note.className = 'small'
  save.onclick = async () => {
    note.textContent = 'Saving...'
    const r = await fetch('/save_json', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ json_file: obj }) })
    const j = await r.json()
    note.textContent = j.ok ? `Saved: ${j.path}` : j.error || 'error'
  }
  row.appendChild(save)
  row.appendChild(note)
  blk.appendChild(row)
  container.appendChild(blk)
}

function renderCodeBlock(code) {
  const cont = document.createElement('div')
  cont.className = 'code-block'
  const rows = document.createElement('div')
  rows.className = 'code-rows'
  const lines = String(code).replace(/\r\n/g, "\n").split("\n")
  for (let i = 0; i < lines.length; i++) {
    const row = document.createElement('div')
    row.className = 'code-row'
    const ln = document.createElement('span')
    ln.className = 'code-ln'
    ln.textContent = String(i + 1)
    const txt = document.createElement('span')
    txt.className = 'code-txt'
    txt.textContent = lines[i] === '' ? '\u200b' : lines[i]
    row.appendChild(ln)
    row.appendChild(txt)
    rows.appendChild(row)
  }
  cont.appendChild(rows)
  return cont
}

function getCodeFromBlock(cont) {
  try {
    const lines = []
    cont.querySelectorAll('.code-row .code-txt').forEach(el => {
      const t = el.textContent.replace(/\u200b/g, '')
      lines.push(t)
    })
    return lines.join('\n')
  } catch (e) { return '' }
}

function showModal() {
  modalEl.style.display = 'flex'
}

/*
startChatBtn.onclick = () => {
  selectedModel = modelSelectEl.value
  modelTag.textContent = 'reviewer: ' + selectedModel + ' • drafter: ' + drafterModel
  conversationId = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2))
  modalEl.style.display = 'none'
}
*/

document.addEventListener('DOMContentLoaded', () => {
  try {
    fetch('/config_models').then(r => r.json()).then(j => {
      if (j && j.drafter_model) drafterModel = j.drafter_model
    }).catch(() => {})
  } catch {}
  // Don't show modal immediately; landing page is shown by default
  // showModal() 
})

function renderContextBar() {
  if (!contextBarEl) return
  if (!contextAdds.length) { contextBarEl.style.display = 'none'; contextBarEl.innerHTML = ''; return }
  contextBarEl.style.display = 'block'
  contextBarEl.innerHTML = ''
  const info = document.createElement('div')
  info.className = 'small'
  info.textContent = 'Context to include in next message:'
  contextBarEl.appendChild(info)
  contextAdds.forEach((item, idx) => {
    const chip = document.createElement('span')
    chip.className = 'context-chip'
    chip.textContent = (item.type === 'file' ? ('file: ' + (item.name || '')) : 'output')
    const x = document.createElement('button')
    x.textContent = '✕'
    x.title = 'remove'
    x.onclick = () => { contextAdds.splice(idx,1); renderContextBar() }
    chip.appendChild(x)
    contextBarEl.appendChild(chip)
  })
}

function showWarn(ctrl) {
  if (!warningBarEl) return
  warningBarEl.style.display = 'flex'
  warningBarEl.innerHTML = ''
  const msg = document.createElement('div')
  msg.textContent = `The LLM has been thinking for more than ${warnMinutes} minutes. Do you wish to stop generation?`
  const actions = document.createElement('div')
  actions.className = 'warn-actions'
  const stop = document.createElement('button')
  stop.textContent = 'Stop'
  stop.onclick = () => { try { ctrl.abort('user cancel') } catch {} hideWarn() }
  const continueBtn = document.createElement('button')
  continueBtn.textContent = 'Continue waiting'
  continueBtn.onclick = () => hideWarn()
  actions.appendChild(stop)
  actions.appendChild(continueBtn)
  warningBarEl.appendChild(msg)
  warningBarEl.appendChild(actions)
}

function hideWarn() {
  if (!warningBarEl) return
  warningBarEl.style.display = 'none'
  warningBarEl.innerHTML = ''
}

function basename(p) {
  const parts = p.split(/[\\/]/)
  return parts[parts.length - 1] || p
}
