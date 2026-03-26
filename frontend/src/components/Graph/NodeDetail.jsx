import React, { useState } from 'react';
import { NODE_META, FLOW_TYPES } from '../../utils/graphConstants';
import './NodeDetail.css';

export default function NodeDetail({ node, onClose, onExpand, onTrace }) {
  const [showAll, setShowAll] = useState(false);
  if (!node) return null;

  const meta      = NODE_META[node.type] || {};
  const data      = node.data || {};
  const entries   = Object.entries(data).filter(([, v]) => v != null && v !== '');
  const visible   = showAll ? entries : entries.slice(0, 12);
  const hidden    = entries.length - 12;
  const isFlow    = FLOW_TYPES.has(node.type);

  return (
    <div className="nd" style={{ '--nd-c': meta.color || '#888', '--nd-bg': meta.bg || '#F5F2ED' }}>

      {/* ── Header bar ── */}
      <div className="nd__header">
        <div className="nd__icon-wrap">
          <div className="nd__icon-dot" />
        </div>
        <div className="nd__title-block">
          <div className="nd__type">{meta.label || node.type}</div>
          <div className="nd__id">{node.label}</div>
        </div>
        <button className="nd__close" onClick={onClose} aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* ── Metadata fields — all of them like reference ── */}
      <div className="nd__fields">
        {/* Entity type row always shown */}
        <div className="nd__field">
          <span className="nd__fk">Entity</span>
          <span className="nd__fv" style={{ color: 'var(--nd-c)' }}>
            {meta.label || node.type}
          </span>
        </div>

        {visible.map(([k, v]) => (
          <div className="nd__field" key={k}>
            <span className="nd__fk">{formatKey(k)}</span>
            <span className="nd__fv">{formatVal(v)}</span>
          </div>
        ))}

        {!showAll && hidden > 0 && (
          <button className="nd__more-btn" onClick={() => setShowAll(true)}>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
            {hidden} additional fields hidden
          </button>
        )}
        {showAll && entries.length > 12 && (
          <button className="nd__more-btn" onClick={() => setShowAll(false)}>
            ↑ Show less
          </button>
        )}
      </div>

      {/* ── Connections count ── */}
      <div className="nd__connections">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3"/>
          <line x1="12" y1="3" x2="12" y2="9"/>
          <line x1="12" y1="15" x2="12" y2="21"/>
          <line x1="3" y1="12" x2="9" y2="12"/>
          <line x1="15" y1="12" x2="21" y2="12"/>
        </svg>
        Connections: {node.connections ?? '—'}
      </div>

      {/* ── Actions ── */}
      <div className="nd__actions">
        <button className="nd__btn nd__btn--primary" onClick={onExpand}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            <line x1="11" y1="8" x2="11" y2="14"/>
            <line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
          Expand Connections
        </button>
        {isFlow && (
          <button className="nd__btn nd__btn--ghost" onClick={onTrace}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
            Trace O2C Flow
          </button>
        )}
      </div>
    </div>
  );
}

function formatKey(k) {
  // CamelCase or snake_case → Title Case With Spaces
  return k
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatVal(v) {
  if (v === null || v === undefined) return '—';
  const s = String(v);
  // ISO date cleanup
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.replace('T00:00:00.000Z', '').replace('T', ' ');
  // Number formatting
  if (!isNaN(v) && String(v).length > 4 && typeof v === 'number') return Number(v).toLocaleString();
  return s;
}
