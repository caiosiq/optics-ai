const messagesEl = document.getElementById('messages')
const inputEl = document.getElementById('input')
const sendBtn = document.getElementById('send')
const testBtn = document.getElementById('test')
const modelTag = document.getElementById('modelTag')
const modalEl = document.getElementById('modal')
const modelSelectEl = document.getElementById('modelSelect')
const startChatBtn = document.getElementById('startChat')
let selectedModel = null
let conversationId = null

function appendBlock(label, content) {
  const wrap = document.createElement('div')
  const isUser = label === 'user'
  wrap.className = `bubble ${isUser ? 'bubble-user' : 'bubble-agent'}`
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = label
  wrap.appendChild(tag)
  const c = document.createElement('div')
  c.textContent = content
  wrap.appendChild(c)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
}

function appendCode(code, meta) {
  const wrap = document.createElement('div')
  wrap.className = 'bubble bubble-agent'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = 'code'
  wrap.appendChild(tag)
  const pre = document.createElement('pre')
  pre.className = 'code'
  pre.textContent = code
  wrap.appendChild(pre)
  const row = document.createElement('div')
  row.className = 'row'
  const run = document.createElement('button')
  run.textContent = 'Run Code'
  const out = document.createElement('div')
  out.className = 'small'
  run.onclick = async () => {
    out.textContent = 'Running...'
    const r = await fetch('/run_code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, code_meta: meta || null }) })
    const j = await r.json()
    out.textContent = j.ok ? (j.output || '[no output]') : j.error || 'error'
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
        wrap.appendChild(img)
      })
    }
    if (j.files && j.files.length) {
      j.files.forEach(path => {
        displayFile(path, wrap)
        const add = document.createElement('button')
        add.textContent = 'Add ' + (path.split('/').pop()) + ' to context'
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
            contextAdds.push({ type: 'file', name: path.split('/').pop(), text: snippet })
            if (contextBarEl) renderContextBar()
          } catch (e) {}
        }
        wrap.appendChild(add)
      })
    }
  }
  row.appendChild(run)
  row.appendChild(out)
  wrap.appendChild(row)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
}

function appendJson(obj) {
  const wrap = document.createElement('div')
  wrap.className = 'bubble bubble-agent'
  const tag = document.createElement('div')
  tag.className = 'tag'
  tag.textContent = 'json_file'
  wrap.appendChild(tag)
  const pre = document.createElement('pre')
  pre.className = 'code'
  pre.textContent = JSON.stringify(obj, null, 2)
  wrap.appendChild(pre)
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
  wrap.appendChild(row)
  messagesEl.appendChild(wrap)
  messagesEl.scrollTop = messagesEl.scrollHeight
}

function renderResponse(r) {
  const o = r.response || {}
  if (o.text) appendBlock('text', o.text)
  if (o.code) appendCode(o.code, o.code_meta)
  if (o.json_file) appendJson(o.json_file)
}

sendBtn.onclick = async () => {
  const v = inputEl.value.trim()
  if (!v) return
  if (!selectedModel) { showModal(); return }
  appendBlock('user', v)
  inputEl.value = ''
  const loading = showLoading()
  const r = await fetch('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: v, model: selectedModel, conversation_id: conversationId }) })
  const j = await r.json()
  if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
  if (!j.ok) {
    appendBlock('error', j.error || 'error')
    if (j.raw_message) appendDebug('raw_message', j.raw_message)
    if (j.raw_response) appendDebug('raw_response', j.raw_response)
    return
  }
  renderResponse(j)
  if (contextBarEl) { contextAdds = []; renderContextBar() }
}

testBtn.onclick = async () => {
  if (!selectedModel) showModal()
  const loading = showLoading()
  const r = await fetch('/test_response')
  const j = await r.json()
  if (loading && loading.parentNode) loading.parentNode.removeChild(loading)
  if (!j.ok) { appendBlock('error', j.error || 'error'); if (j.raw_message) appendDebug('raw_message', j.raw_message); if (j.raw_response) appendDebug('raw_response', j.raw_response); return }
  renderResponse(j)
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
  const name = path.split('/').pop()
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
    a.textContent = 'Open ' + name
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

function showModal() {
  modalEl.style.display = 'flex'
}

startChatBtn.onclick = () => {
  selectedModel = modelSelectEl.value
  modelTag.textContent = 'model: ' + selectedModel
  conversationId = crypto.randomUUID ? crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(16).slice(2))
  modalEl.style.display = 'none'
}

document.addEventListener('DOMContentLoaded', () => {
  showModal()
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
