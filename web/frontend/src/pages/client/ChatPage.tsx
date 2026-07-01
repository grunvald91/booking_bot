import { useState, useRef, useEffect, useCallback } from 'react'
import { Bot, Send, Check, X, Loader2 } from 'lucide-react'
import { api } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  text: string
  pending_action?: {
    action_id: string
    description: string
    tool_name: string
  }
  actionHandled?: boolean
}

function formatMessage(text: string) {
  // Bold **text**
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={i} style={{ fontWeight: 600 }}>
          {part.slice(2, -2)}
        </strong>
      )
    }
    // Split by newlines
    const lines = part.split('\n')
    return lines.map((line, j) => (
      <span key={`${i}-${j}`}>
        {j > 0 && <br />}
        {line}
      </span>
    ))
  })
}

const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  role: 'ai',
  text: 'Привет! Я AI-помощник. Помогу записаться, проверить свободное время или управлять записями. Что вам нужно?',
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, loading, scrollToBottom])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      text,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.aiChat(text)
      const aiMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'ai',
        text: res.reply,
        pending_action: res.pending_action,
      }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
      const errMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'ai',
        text: 'Произошла ошибка. Попробуйте ещё раз.',
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async (actionId: string, msgId: string) => {
    setConfirmingId(actionId)
    try {
      const res = await api.aiConfirm(actionId)
      // Mark action as handled
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, actionHandled: true } : m))
      )
      // Add result message
      const resultMsg: ChatMessage = {
        id: Date.now().toString(),
        role: 'ai',
        text: res.reply,
      }
      setMessages((prev) => [...prev, resultMsg])
    } catch {
      const errMsg: ChatMessage = {
        id: Date.now().toString(),
        role: 'ai',
        text: 'Не удалось выполнить действие. Попробуйте ещё раз.',
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setConfirmingId(null)
    }
  }

  const handleReject = async (actionId: string, msgId: string) => {
    setConfirmingId(actionId)
    try {
      await api.aiReject(actionId)
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, actionHandled: true } : m))
      )
      const cancelMsg: ChatMessage = {
        id: Date.now().toString(),
        role: 'ai',
        text: 'Действие отменено.',
      }
      setMessages((prev) => [...prev, cancelMsg])
    } catch {
      // ignore
    } finally {
      setConfirmingId(null)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <ClientShell title="AI-помощник">
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Messages area — scrolls independently within the shell's content area */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12, padding: '14px 0' }}>
          {messages.map((msg) => (
            <div key={msg.id}>
              {msg.role === 'ai' ? (
                <div style={{ display: 'flex', gap: 8, maxWidth: '85%' }}>
                  <div
                    style={{
                      width: 28, height: 28, borderRadius: '50%', flexShrink: 0, marginTop: 4,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: 'var(--s-accent-soft)',
                    }}
                  >
                    <Bot size={16} style={{ color: 'var(--s-accent)' }} />
                  </div>
                  <div>
                    <div
                      className="ds-text"
                      style={{
                        background: 'var(--s-surface-2)', color: 'var(--s-text)',
                        borderRadius: 16, borderTopLeftRadius: 4,
                        padding: '10px 14px',
                      }}
                    >
                      {formatMessage(msg.text)}
                    </div>
                    {/* Pending action card */}
                    {msg.pending_action && !msg.actionHandled && (
                      <div
                        style={{
                          marginTop: 8, borderRadius: 16,
                          padding: '12px 14px',
                          background: 'color-mix(in srgb, var(--s-warning) 12%, var(--s-surface))',
                          border: '1px solid color-mix(in srgb, var(--s-warning) 35%, transparent)',
                        }}
                      >
                        <p className="ds-text" style={{ fontWeight: 600, marginBottom: 10, color: 'var(--s-text)' }}>
                          {msg.pending_action.description}
                        </p>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => handleConfirm(msg.pending_action!.action_id, msg.id)}
                            disabled={confirmingId === msg.pending_action.action_id}
                            className="ds-btn ds-btn--primary ds-btn--sm"
                          >
                            {confirmingId === msg.pending_action.action_id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <Check size={14} />
                            )}
                            Подтвердить
                          </button>
                          <button
                            onClick={() => handleReject(msg.pending_action!.action_id, msg.id)}
                            disabled={confirmingId === msg.pending_action.action_id}
                            className="ds-btn ds-btn--ghost ds-btn--sm"
                          >
                            <X size={14} />
                            Отмена
                          </button>
                        </div>
                      </div>
                    )}
                    {msg.pending_action && msg.actionHandled && (
                      <div
                        style={{
                          marginTop: 8, borderRadius: 16, padding: '10px 14px',
                          background: 'var(--s-surface-2)', border: '1px solid var(--s-line)',
                        }}
                      >
                        <p className="ds-caption" style={{ textDecoration: 'line-through' }}>
                          {msg.pending_action.description}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <div
                    className="ds-text"
                    style={{
                      background: 'var(--s-accent)', color: 'var(--s-accent-ink)',
                      borderRadius: 16, borderTopRightRadius: 4,
                      padding: '10px 14px', maxWidth: '85%',
                    }}
                  >
                    {formatMessage(msg.text)}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Loading indicator */}
          {loading && (
            <div style={{ display: 'flex', gap: 8, maxWidth: '85%' }}>
              <div
                style={{
                  width: 28, height: 28, borderRadius: '50%', flexShrink: 0, marginTop: 4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: 'var(--s-accent-soft)',
                }}
              >
                <Bot size={16} style={{ color: 'var(--s-accent)' }} />
              </div>
              <div style={{ background: 'var(--s-surface-2)', borderRadius: 16, borderTopLeftRadius: 4, padding: '12px 14px' }}>
                <div style={{ display: 'flex', gap: 6 }}>
                  <div className="animate-bounce" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--s-muted-2)', animationDelay: '0ms' }} />
                  <div className="animate-bounce" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--s-muted-2)', animationDelay: '150ms' }} />
                  <div className="animate-bounce" style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--s-muted-2)', animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area — pinned to the bottom of the visible area */}
        <div style={{ flexShrink: 0, paddingTop: 10 }}>
          <div className="ds-search" style={{ borderRadius: 999, paddingRight: 6 }}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Напишите сообщение..."
              disabled={loading}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              className="ds-icon-btn"
              style={{
                width: 34, height: 34, borderRadius: '50%',
                background: 'var(--s-accent)', color: 'var(--s-accent-ink)',
                opacity: !input.trim() || loading ? 0.4 : 1,
              }}
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </ClientShell>
  )
}
