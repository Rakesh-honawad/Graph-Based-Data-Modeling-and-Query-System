import React from 'react';
import './TopBar.css';

const FLOW_STEPS = [
  { key: 'SalesOrder',   label: 'Sales Order',   color: '#4267B8' },
  { key: 'Delivery',     label: 'Delivery',       color: '#2D7D52' },
  { key: 'BillingDoc',   label: 'Billing Doc',    color: '#B86E1A' },
  { key: 'Payment',      label: 'Payment',        color: '#7B4BAD' },
  { key: 'JournalEntry', label: 'Journal Entry',  color: '#C0404A' },
];

export default function TopBar({ stats, onReset, connected }) {
  return (
    <header className="topbar">
      {/* Brand block */}
      <div className="topbar__brand">
        <div className="topbar__wordmark">
          <span className="topbar__title">O2C</span>
          <span className="topbar__sub">Intelligence</span>
        </div>
        <div className="topbar__divider" />
        <span className="topbar__desc">Order-to-Cash Graph System</span>
      </div>

      {/* O2C Flow chain — visual pipeline */}
      <div className="topbar__flow">
        {FLOW_STEPS.map((step, i) => (
          <React.Fragment key={step.key}>
            <div className="flow-step" style={{ '--step-color': step.color }}>
              <div className="flow-step__dot" />
              <span className="flow-step__label">{step.label}</span>
              {stats && (
                <span className="flow-step__count">
                  {getStepCount(stats, step.key)}
                </span>
              )}
            </div>
            {i < FLOW_STEPS.length - 1 && (
              <div className="flow-arrow">
                <svg width="14" height="10" viewBox="0 0 14 10" fill="none">
                  <path d="M1 5h11M8 1l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Actions */}
      <div className="topbar__actions">
        <div className={`topbar__status ${connected ? 'topbar__status--ok' : 'topbar__status--err'}`}>
          <div className="topbar__status-dot" />
          <span>{connected ? 'Connected' : 'Offline'}</span>
        </div>
        <button className="topbar__reset-btn" onClick={onReset} title="Reset graph view">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          Reset
        </button>
      </div>
    </header>
  );
}

function getStepCount(stats, type) {
  const map = {
    SalesOrder:   stats.total_sales_orders,
    Delivery:     stats.total_deliveries,
    BillingDoc:   stats.total_billing_docs,
    Payment:      stats.total_payments,
    JournalEntry: null,
  };
  const v = map[type];
  if (v == null) return null;
  return <span className="flow-step__num">{v}</span>;
}
