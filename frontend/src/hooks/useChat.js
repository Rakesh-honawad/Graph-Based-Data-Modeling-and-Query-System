import { useState, useCallback, useRef } from 'react';
import { chatApi } from '../utils/api';

const mkId = () => 'id_' + Math.random().toString(36).slice(2, 9);

const WELCOME = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hi — I can answer questions about your Order-to-Cash dataset. " +
    "Try asking about sales orders, billing documents, deliveries, payments, or broken flows.\n\n" +
    "Click any node on the graph to inspect it, or type below.",
  ts: Date.now(),
};

export function useChat({ onHighlight }) {
  const [messages, setMessages] = useState([WELCOME]);
  const [status, setStatus]     = useState('idle'); // idle | thinking | error
  const sessionRef = useRef(mkId());

  const send = useCallback(async (question) => {
    if (!question.trim() || status === 'thinking') return;

    const userMsg = { id: mkId(), role: 'user', content: question, ts: Date.now() };
    setMessages(m => [...m, userMsg]);
    setStatus('thinking');

    try {
      const data = await chatApi.ask(question, sessionRef.current);

      const asstMsg = {
        id:             mkId(),
        role:           'assistant',
        content:        data.answer,
        sql:            data.sql || null,
        rows:           data.rows || [],
        highlighted:    data.highlighted_nodes || [],
        outOfDomain:    !!data.out_of_domain,
        error:          data.error || null,
        provider:       data.provider || null,
        ts:             Date.now(),
      };

      setMessages(m => [...m, asstMsg]);
      setStatus('idle');

      if (asstMsg.highlighted.length) {
        onHighlight?.(new Set(asstMsg.highlighted));
      }
    } catch (err) {
      setMessages(m => [...m, {
        id:      mkId(),
        role:    'assistant',
        content: `Connection error — is the backend running? (${err.message})`,
        error:   'connection',
        ts:      Date.now(),
      }]);
      setStatus('error');
    }
  }, [status, onHighlight]);

  const clear = useCallback(() => {
    chatApi.clear(sessionRef.current).catch(() => {});
    sessionRef.current = mkId();
    setMessages([WELCOME]);
    setStatus('idle');
    onHighlight?.(new Set());
  }, [onHighlight]);

  return { messages, status, send, clear };
}
