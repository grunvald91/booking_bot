import { useState, useRef, useEffect, useCallback } from 'react'
import { Bot, Send, Check, X, Loader2 } from 'lucide-react'
import { api } from '../../api/client'

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
        <strong key={i} className="font-semibold">
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
    <div className="flex flex-col -mx-4 sm:-mx-6 -mt-6 -mb-24" style={{ height: 'calc(100dvh - 56px - 56px)' }}>
      {/* Messages area — scrollable */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <div key={msg.id}>
            {msg.role === 'ai' ? (
              <div className="flex gap-2 max-w-[85%]">
                <div className="w-7 h-7 rounded-full bg-apple-blue/10 flex items-center justify-center flex-shrink-0 mt-1">
                  <Bot size={16} className="text-apple-blue" />
                </div>
                <div>
                  <div className="bg-gray-100 rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm text-apple-text">
                    {formatMessage(msg.text)}
                  </div>
                  {/* Pending action card */}
                  {msg.pending_action && !msg.actionHandled && (
                    <div className="mt-2 bg-amber-50 border border-amber-200 rounded-2xl px-4 py-3">
                      <p className="text-sm font-medium text-amber-900 mb-2">
                        {msg.pending_action.description}
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleConfirm(msg.pending_action!.action_id, msg.id)}
                          disabled={confirmingId === msg.pending_action.action_id}
                          className="flex items-center gap-1.5 bg-apple-blue text-white text-sm font-medium px-4 py-2 rounded-full hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
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
                          className="flex items-center gap-1.5 bg-white border border-apple-border text-apple-gray text-sm font-medium px-4 py-2 rounded-full hover:bg-gray-50 transition-all duration-200 disabled:opacity-50"
                        >
                          <X size={14} />
                          Отмена
                        </button>
                      </div>
                    </div>
                  )}
                  {msg.pending_action && msg.actionHandled && (
                    <div className="mt-2 bg-gray-50 border border-gray-200 rounded-2xl px-4 py-2.5">
                      <p className="text-xs text-apple-gray line-through">
                        {msg.pending_action.description}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex justify-end">
                <div className="bg-apple-blue text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm max-w-[85%]">
                  {formatMessage(msg.text)}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex gap-2 max-w-[85%]">
            <div className="w-7 h-7 rounded-full bg-apple-blue/10 flex items-center justify-center flex-shrink-0 mt-1">
              <Bot size={16} className="text-apple-blue" />
            </div>
            <div className="bg-gray-100 rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1.5">
                <div className="w-2 h-2 bg-apple-gray/40 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-apple-gray/40 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-apple-gray/40 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area — glued to bottom */}
      <div className="shrink-0 bg-white border-t border-apple-border/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Напишите сообщение..."
            className="flex-1 bg-gray-100 rounded-full px-5 py-2.5 text-sm text-apple-text placeholder:text-apple-gray/50 outline-none focus:ring-2 focus:ring-apple-blue/30 transition-all duration-200"
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || loading}
            className="w-10 h-10 rounded-full bg-apple-blue text-white flex items-center justify-center hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-30 disabled:hover:bg-apple-blue flex-shrink-0"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  )
}
