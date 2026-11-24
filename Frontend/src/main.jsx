import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, ArrowUp, ChevronDown, CircleHelp, Command, Copy, Ellipsis, FileText, Link as LinkIcon, Moon, Plus, RotateCcw, Sparkles, Sun, Trash2, Zap } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import './styles.css'

const MODELS = [
  { id: 'groq/openai/gpt-oss-20b', label: 'GPT-OSS 20B', provider: 'Groq' },
  { id: 'groq/openai/gpt-oss-120b', label: 'GPT-OSS 120B', provider: 'Groq' },
  { id: 'gemini/gemini-3.5-flash', label: 'Gemini 3.5 Flash', provider: 'Google' },
  { id: 'ollama/qwen3:0.6b', label: 'Qwen3 · 0.6B', provider: 'Ollama' },
]

const extractPdfText = async (file) => {
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc = `${pdfWorkerUrl}?v=2`
  const document = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise
  const pages = []
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber)
    const content = await page.getTextContent()
    pages.push(content.items.map(item => 'str' in item ? item.str : '').join(' '))
  }
  return pages.join('\n').slice(0, 50000)
}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const newSessionId = () => `s-${crypto.randomUUID().slice(0, 8)}`
const fetchSessions = async () => {
  const response = await fetch(`${API_URL}/sessions`)
  if (!response.ok) throw new Error('Could not load your conversations.')
  return (await response.json()).sessions
}
const fetchSessionMessages = async (id) => {
  const response = await fetch(`${API_URL}/sessions/${encodeURIComponent(id)}/messages`)
  if (!response.ok) throw new Error('Could not load this conversation.')
  return response.json()
}
const formatRelativeTime = (value) => {
  const elapsed = Date.now() - new Date(value).getTime()
  if (!Number.isFinite(elapsed) || elapsed < 0) return ''
  if (elapsed < 60_000) return 'now'
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}m`
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}h`
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function App() {
  const [sessionId, setSessionId] = useState(newSessionId)
  const [sessions, setSessions] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [sending, setSending] = useState(false)
  const [apiState, setApiState] = useState('checking')
  const [theme, setTheme] = useState('light')
  const [selectedModel, setSelectedModel] = useState(MODELS[0])
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [showAttachmentMenu, setShowAttachmentMenu] = useState(false)
  const [showLinkInput, setShowLinkInput] = useState(false)
  const [linkDraft, setLinkDraft] = useState('')
  const [attachments, setAttachments] = useState([])
  const [attachmentError, setAttachmentError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [historyLoading, setHistoryLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const endRef = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  useEffect(() => {
    let active = true
    fetch(`${API_URL}/health`)
      .then(response => response.ok ? response.json() : Promise.reject())
      .then(() => { if (active) setApiState('online') })
      .catch(() => { if (active) setApiState('offline') })
    const loadRecentSession = async () => {
      try {
        const savedSessions = await fetchSessions()
        if (!active) return
        setSessions(savedSessions)
        if (savedSessions.length) {
          const recent = await fetchSessionMessages(savedSessions[0].session_id)
          if (!active) return
          setSessionId(savedSessions[0].session_id)
          setMessages(recent.messages)
          setSystemPrompt(recent.system_prompt || '')
        }
      } catch (error) {
        if (active) setHistoryError(error.message)
      } finally {
        if (active) setHistoryLoading(false)
      }
    }
    loadRecentSession()
    return () => { active = false }
  }, [])
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  const startNewChat = () => {
    if (sending || historyLoading) return
    setSessionId(newSessionId())
    setMessages([])
    setInput('')
    setSystemPrompt('')
    setAttachments([])
    setAttachmentError('')
    setShowSettings(false)
    setShowLinkInput(false)
    setLinkDraft('')
    setHistoryError('')
  }
  const refreshSessions = async () => {
    try {
      setSessions(await fetchSessions())
      setHistoryError('')
    } catch (error) {
      setHistoryError(error.message)
    }
  }
  const openSession = async (id) => {
    if (sending || historyLoading || id === sessionId) return
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const data = await fetchSessionMessages(id)
      setSessionId(data.session_id)
      setMessages(data.messages)
      setInput('')
      setSystemPrompt(data.system_prompt || '')
      setAttachments([])
      setAttachmentError('')
      setShowSettings(false)
      setShowLinkInput(false)
      setLinkDraft('')
    } catch (error) {
      setHistoryError(error.message)
    } finally {
      setHistoryLoading(false)
    }
  }
  const addPdfFiles = async (event) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    setAttachmentError('')
    for (const file of files) {
      if (file.type !== 'application/pdf') {
        setAttachmentError('Choose a PDF file to attach.')
        continue
      }
      if (file.size > 10 * 1024 * 1024) {
        setAttachmentError(`${file.name} is larger than the 10 MB limit.`)
        continue
      }
      try {
        const text = await extractPdfText(file)
        if (!text.trim()) {
          setAttachmentError(`${file.name} contains no selectable text.`)
          continue
        }
        setAttachments(current => [...current, { id: crypto.randomUUID(), type: 'pdf', name: file.name, text }])
      } catch {
        setAttachmentError(`Could not read ${file.name}. Try another PDF.`)
      }
    }
    setShowAttachmentMenu(false)
  }
  const addLink = (event) => {
    event.preventDefault()
    try {
      const url = new URL(linkDraft.trim())
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error()
      setAttachments(current => [...current, { id: crypto.randomUUID(), type: 'link', name: url.hostname, url: url.toString() }])
      setLinkDraft('')
      setShowLinkInput(false)
      setShowAttachmentMenu(false)
      setAttachmentError('')
    } catch {
      setAttachmentError('Enter a valid http or https link.')
    }
  }
  const sendMessage = async (event) => {
    event?.preventDefault()
    const message = input.trim()
    if (!message || sending) return
    setInput('')
    setMessages(current => [...current, { role: 'user', content: message }])
    setSending(true)
    try {
      const documentContext = attachments.filter(item => item.type === 'pdf').map(item => `PDF: ${item.name}\n${item.text}`).join('\n\n')
      const contextLinks = attachments.filter(item => item.type === 'link').map(item => item.url)
      const promptParts = [
        systemPrompt.trim(),
        documentContext && `Use the following attached PDF content as context:\n${documentContext}`,
        contextLinks.length && `The user attached these reference URLs as context. Use them when available:\n${contextLinks.join('\n')}`,
      ].filter(Boolean)
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          model: selectedModel.id,
          system_prompt: promptParts.join('\n\n'),
          ...(contextLinks.length ? { context_links: contextLinks } : {}),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.')
      setMessages(current => [...current, { role: 'assistant', content: data.reply, metadata: data.metadata }])
      setApiState('online')
      refreshSessions()
    } catch (error) {
      setMessages(current => [...current, { role: 'error', content: error.message || 'Unable to reach the assistant. Check your connection and try again.' }])
      setApiState('offline')
    } finally { setSending(false) }
  }

  const copyReply = async (text) => { await navigator.clipboard?.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1400) }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" aria-label="Lyftr home"><span className="brand-mark"><Activity size={17} strokeWidth={2.6}/></span><span>lyftr<span className="brand-period">.</span></span></a>
      <button className="new-chat" onClick={startNewChat} disabled={sending || historyLoading}><Plus size={17}/><span>New chat</span><kbd><Command size={11}/> K</kbd></button>
      <div className="nav-caption">WORKSPACE</div>
      <button className="nav-item active"><span className="nav-icon"><Sparkles size={16}/></span>AI assistant</button>
      <div className="nav-caption recent-label">RECENT</div>
      <div className="history-list" aria-label="Recent conversations">
        {historyLoading && sessions.length === 0 && <p className="history-message">Loading chats…</p>}
        {!historyLoading && sessions.length === 0 && <p className="history-message">Your conversations will appear here.</p>}
        {sessions.map(session => <button
          className={`history-item ${session.session_id === sessionId ? 'selected' : ''}`}
          key={session.session_id}
          type="button"
          title={session.title || 'New chat'}
          aria-current={session.session_id === sessionId ? 'page' : undefined}
          disabled={sending || historyLoading}
          onClick={() => openSession(session.session_id)}
        >
          <span className="history-dot"/>
          <span className="history-title">{session.title || 'New chat'}</span>
          <span className="history-time">{formatRelativeTime(session.updated_at)}</span>
        </button>)}
        {historyError && <p className="history-message history-error" role="status">{historyError}</p>}
      </div>
      <div className="sidebar-bottom">
        <div className="usage-card"><div className="usage-title"><span>Inference status</span><span className={`status-dot ${apiState}`}/></div><div className="usage-subtitle">{apiState === 'online' ? 'All systems operational' : apiState === 'checking' ? 'Checking connection…' : 'Backend unavailable'}</div><div className="usage-foot"><span><Zap size={13}/> Powered by Lyftr AI</span><span className="usage-indicator"/></div></div>
        <button className="profile"><span className="avatar">L</span><span className="profile-name">Lyftr workspace<small>Free plan</small></span><Ellipsis size={17} className="profile-more"/></button>
      </div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><span className="crumb-current">AI assistant</span></div><div className="top-actions"><span className={`connection-pill ${apiState}`}><span/> {apiState === 'online' ? 'Connected' : apiState === 'checking' ? 'Connecting' : 'Offline'}</span><button className="icon-button" onClick={() => setTheme(current => current === 'light' ? 'dark' : 'light')} aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}>{theme === 'light' ? <Moon size={16}/> : <Sun size={16}/>}</button><button className="icon-button" aria-label="Help"><CircleHelp size={17}/></button><span className="top-avatar">L</span></div></header>
      <section className={`conversation ${messages.length ? 'has-messages' : ''}`} aria-label="Chat conversation">
        {messages.length === 0 ? <div className="welcome"><div className="welcome-kicker"><span className="sparkle-mark"><Sparkles size={14}/></span> YOUR AI WORKSPACE</div><h1>Ideas start<br/>somewhere<span className="heading-period">.</span></h1><p className="welcome-copy">A thoughtful space to think out loud, explore a question, or get unstuck on what&apos;s next.</p><div className="prompt-grid">
          <button onClick={() => setInput('What makes a great product experience?')} className="prompt-card"><span className="prompt-icon violet"><Sparkles size={16}/></span><span className="prompt-title">Explore an idea</span><span className="prompt-desc">Help me think through a new concept</span><ArrowUp className="prompt-arrow" size={15}/></button>
          <button onClick={() => setInput('Explain a complex topic in simple terms.')} className="prompt-card"><span className="prompt-icon amber"><Command size={16}/></span><span className="prompt-title">Learn something</span><span className="prompt-desc">Make a complicated topic feel simple</span><ArrowUp className="prompt-arrow" size={15}/></button>
          <button onClick={() => setInput('Help me write a clear, compelling introduction.')} className="prompt-card"><span className="prompt-icon mint"><Activity size={16}/></span><span className="prompt-title">Make something</span><span className="prompt-desc">Turn a blank page into a first draft</span><ArrowUp className="prompt-arrow" size={15}/></button>
        </div></div> : <div className="message-list">{messages.map((message, index) => message.role === 'user' ? <div className="user-row" key={index}><div className="user-bubble">{message.content}</div><span className="user-avatar">Y</span></div> : message.role === 'error' ? <div className="error-row" key={index}><div className="assistant-avatar"><Activity size={15}/></div><div className="error-content"><strong>We couldn&apos;t complete that</strong><p>{message.content}</p><button onClick={() => setInput('')} className="retry-button"><RotateCcw size={13}/> Try again</button></div></div> : <article className="assistant-row" data-testid="assistant-message" key={index}><div className="assistant-avatar"><Activity size={15}/></div><div className="assistant-content"><div className="assistant-name">Lyftr <span>·</span> assistant</div><div className="reply-text markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>{message.metadata && <div className="metadata"><span className={`source-tag ${message.metadata.resolution_source === 'LLM_CACHE' ? 'cached' : ''}`} data-testid="meta-source"><span className="source-dot"/>{message.metadata.resolution_source}</span><span className="meta-divider"/><span className="meta-value" data-testid="meta-model">{message.metadata.model}</span><span className="meta-value" data-testid="meta-latency">{message.metadata.latency_ms} ms</span><span className="meta-value token-value"><span>IN</span><b data-testid="meta-input-tokens">{message.metadata.input_tokens}</b></span><span className="meta-value token-value"><span>OUT</span><b data-testid="meta-output-tokens">{message.metadata.output_tokens}</b></span></div>}<div className="reply-actions"><button onClick={() => copyReply(message.content)} aria-label="Copy reply"><Copy size={13}/>{copied ? 'Copied' : 'Copy'}</button><button aria-label="More reply options"><Ellipsis size={15}/></button></div></div></article>)}</div>}
        {sending && <div className="assistant-row loading-row"><div className="assistant-avatar"><Activity size={15}/></div><div className="typing-indicator"><span/><span/><span/><small>Thinking through it</small></div></div>}
        <div ref={endRef}/>
      </section>
      <div className="composer-wrap"><div className="composer-card">
        <input ref={fileInputRef} className="file-input-hidden" type="file" accept="application/pdf,.pdf" multiple onChange={addPdfFiles} aria-label="Choose PDF files"/>
        <textarea data-testid="chat-input" aria-label="Message the assistant" placeholder="Message Lyftr..." rows="1" value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) sendMessage(event) }} disabled={sending || historyLoading}/>
        {attachments.length > 0 && <div className="attachment-chips" aria-label="Attached context">{attachments.map(item => <span className="attachment-chip" key={item.id}>{item.type === 'pdf' ? <FileText size={12}/> : <LinkIcon size={12}/>}<span>{item.name}</span><button type="button" onClick={() => setAttachments(current => current.filter(attachment => attachment.id !== item.id))} aria-label={`Remove ${item.name}`}><Trash2 size={12}/></button></span>)}</div>}
        {attachmentError && <p className="attachment-error" role="status">{attachmentError}</p>}
        <div className="composer-toolbar"><div className="composer-options">
          <div className="composer-control">
            <button type="button" className="composer-option attach-option" onClick={() => { setShowAttachmentMenu(current => !current); setShowModelMenu(false) }} aria-label="Add link or PDF context" aria-expanded={showAttachmentMenu}><Plus size={15}/></button>
            {showAttachmentMenu && <div className="composer-popover attachment-menu"><button type="button" onClick={() => { setShowLinkInput(true); setShowAttachmentMenu(false) }}><LinkIcon size={14}/> Add a link</button><button type="button" onClick={() => fileInputRef.current?.click()}><FileText size={14}/> Upload PDF</button><span>PDFs up to 10 MB</span></div>}
          </div>
          <div className="composer-control">
            <button type="button" className="composer-option" onClick={() => { setShowModelMenu(current => !current); setShowAttachmentMenu(false) }} aria-expanded={showModelMenu} aria-haspopup="listbox"><span className="model-dot"/> {selectedModel.label} <ChevronDown size={13}/></button>
            {showModelMenu && <div className="composer-popover model-menu" role="listbox" aria-label="Choose a model">{MODELS.map(model => <button type="button" role="option" aria-selected={selectedModel.id === model.id} key={model.id} onClick={() => { setSelectedModel(model); setShowModelMenu(false) }}><span>{model.label}</span><small>{model.provider}</small></button>)}</div>}
          </div>
          <span className="option-separator"/><button type="button" className="context-label context-settings" onClick={() => setShowSettings(current => !current)} aria-expanded={showSettings}>System prompt</button>
        </div><div className="send-controls"><span className="enter-hint">↵ to send</span><button data-testid="send-button" className="send-button" aria-label="Send message" onClick={sendMessage} disabled={!input.trim() || sending || historyLoading}>{sending ? <span className="send-spinner"/> : <ArrowUp size={17}/>}</button></div></div></div>
        {showLinkInput && <form className="link-form" onSubmit={addLink}><label htmlFor="context-link-input">Add a context link</label><input id="context-link-input" type="url" placeholder="https://example.com" value={linkDraft} onChange={event => setLinkDraft(event.target.value)} autoFocus/><div><button type="button" onClick={() => { setShowLinkInput(false); setLinkDraft('') }}>Cancel</button><button type="submit">Attach link</button></div></form>}
        {showSettings && <div className="settings-panel"><label htmlFor="system-prompt-input">System prompt <span>Optional</span></label><textarea id="system-prompt-input" data-testid="system-prompt-input" placeholder="Set a tone or give the assistant context for this chat..." rows="3" value={systemPrompt} onChange={event => setSystemPrompt(event.target.value)}/><div className="settings-hint">Applied to each message in this session.</div></div>}
        <div className="composer-footnote">Lyftr can make mistakes. Check important information.</div></div>
    </main>
  </div>
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>)
