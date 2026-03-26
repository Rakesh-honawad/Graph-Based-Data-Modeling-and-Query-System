import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useChat } from '../../hooks/useChat';
import { SUGGESTED_QUERIES } from '../../utils/graphConstants';
import './ChatPanel.css';

export default function ChatPanel({ onHighlight, onExpandNode }) {
  const [input, setInput]   = useState('');
  const endRef              = useRef(null);
  const taRef               = useRef(null);

  const { messages, status, send, clear } = useChat({ onHighlight });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  const handleSend = useCallback(() => {
    if (!input.trim() || status === 'thinking') return;
    send(input.trim());
    setInput('');
    if (taRef.current) taRef.current.style.height = 'auto';
  }, [input, status, send]);

  const handleKey = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  const handleInput = useCallback((e) => {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 96) + 'px';
  }, []);

  return (
    <aside className="chat-panel">

      {/* ── Header ── */}
      <div className="chat-header">
        <div className="chat-header__left">
          <div className="chat-header__dot" />
          <div>
            <div className="chat-header__title">Query Assistant</div>
            <div className="chat-header__sub">NL → SQL · O2C data only</div>
          </div>
        </div>
        <button className="chat-clear icon-btn" onClick={clear} title="New conversation">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
      </div>

      {/* ── Suggestions ── */}
      <div className="chat-chips">
        <p className="section-label" style={{ marginBottom: 6 }}>Quick queries</p>
        <div className="chat-chips__scroll">
          {SUGGESTED_QUERIES.map(q => (
            <button key={q} className="chip" onClick={() => send(q)}>{q}</button>
          ))}
        </div>
      </div>

      {/* ── Messages ── */}
      <div className="chat-messages">
        {messages.map((m, i) => (
          <Message key={m.id} msg={m} idx={i} onExpandNode={onExpandNode} />
        ))}

        {status === 'thinking' && (
          <div className="msg msg--asst">
            <div className="msg__avatar">AI</div>
            <div className="msg__body">
              <div className="typing">
                <span /><span /><span />
              </div>
            </div>
          </div>
        )}

        <div ref={endRef} />
      </div>

      {/* ── Input ── */}
      <div className="chat-input">
        <textarea
          ref={taRef}
          className="chat-input__ta"
          placeholder="Ask about orders, billing, payments…"
          value={input}
          onChange={handleInput}
          onKeyDown={handleKey}
          rows={1}
          disabled={status === 'thinking'}
        />
        <button
          className="chat-input__send"
          onClick={handleSend}
          disabled={!input.trim() || status === 'thinking'}
          aria-label="Send"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
    </aside>
  );
}

/* ── Individual message ── */
function Message({ msg, idx, onExpandNode }) {
  const [showSql, setShowSql] = useState(false);
  const isUser = msg.role === 'user';

  return (
    <div
      className={`msg msg--${isUser ? 'user' : 'asst'} ${msg.outOfDomain ? 'msg--ood' : ''} ${msg.error ? 'msg--err' : ''}`}
      style={{ animationDelay: `${idx * 20}ms` }}
    >
      {!isUser && <div className="msg__avatar">AI</div>}

      <div className="msg__body">
        <div className="msg__bubble">
          <p className="msg__text">{msg.content}</p>

          {/* SQL toggle */}
          {msg.sql && !msg.outOfDomain && (
            <button className="msg__sql-toggle" onClick={() => setShowSql(s => !s)}>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
              </svg>
              {showSql ? 'Hide SQL' : 'View SQL'}
            </button>
          )}
          {showSql && msg.sql && (
            <pre className="msg__sql">{msg.sql}</pre>
          )}
        </div>

        {/* Results table */}
        {msg.rows?.length > 0 && (
          <div className="msg__table-wrap">
            <div className="msg__table-scroll">
              <table className="msg__table">
                <thead>
                  <tr>
                    {Object.keys(msg.rows[0]).map(c => <th key={c}>{c.replace(/_/g, ' ')}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {msg.rows.slice(0, 15).map((row, i) => (
                    <tr key={i}>
                      {Object.values(row).map((v, j) => <td key={j}>{v ?? '—'}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {msg.rows.length > 15 && (
              <p className="msg__table-more">+{msg.rows.length - 15} more rows</p>
            )}
          </div>
        )}

        {/* Highlight badge */}
        {msg.highlighted?.length > 0 && (
          <button
            className="msg__hl-badge"
            onClick={() => onExpandNode?.(msg.highlighted[0])}
          >
            <span className="msg__hl-dot" />
            {msg.highlighted.length} nodes highlighted — click to explore
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </button>
        )}

        {/* Provider */}
        {msg.provider && !isUser && (
          <span className="msg__provider mono">via {msg.provider}</span>
        )}
      </div>

      {isUser && <div className="msg__avatar msg__avatar--user">You</div>}
    </div>
  );
}
