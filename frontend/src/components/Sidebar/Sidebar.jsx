import React, { useState, useRef, useCallback } from 'react';
import { NODE_META } from '../../utils/graphConstants';
import { graphApi } from '../../utils/api';
import './Sidebar.css';

export default function Sidebar({ stats, nodeTypes, filterType, onFilterChange, onExpandNode }) {
  const [query, setQuery]     = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const timerRef = useRef(null);

  const handleInput = useCallback((e) => {
    const q = e.target.value;
    setQuery(q);
    clearTimeout(timerRef.current);
    if (q.length < 2) { setResults([]); return; }
    timerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await graphApi.search(q, 8);
        setResults(data.results || []);
      } catch { setResults([]); }
      finally { setSearching(false); }
    }, 280);
  }, []);

  const totalNodes = nodeTypes.reduce((s, t) => s + (t.count || 0), 0);

  return (
    <aside className="sidebar">

      {/* ── Search ── */}
      <section className="sb-section">
        <p className="section-label">Search</p>
        <div className="sb-search">
          <svg className="sb-search__icon" viewBox="0 0 20 20" fill="none">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M14.5 14.5L18 18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <input
            className="sb-search__input"
            type="text"
            value={query}
            onChange={handleInput}
            placeholder="Search node ID or name…"
          />
          {searching && <div className="sb-search__spinner spinner" />}
        </div>

        {results.length > 0 && (
          <div className="sb-results">
            {results.map(r => (
              <button
                key={r.node_id}
                className="sb-result"
                onClick={() => { onExpandNode?.(r.node_id); setQuery(''); setResults([]); }}
              >
                <span
                  className="sb-result__dot"
                  style={{ background: NODE_META[r.type]?.color || '#888' }}
                />
                <span className="sb-result__label truncate">{r.label}</span>
                <span className="sb-result__type">{r.type}</span>
              </button>
            ))}
          </div>
        )}
        {query.length >= 2 && !searching && results.length === 0 && (
          <p className="sb-no-results">No nodes found</p>
        )}
      </section>

      <div className="divider" />

      {/* ── Node type filter ── */}
      <section className="sb-section">
        <p className="section-label">Filter nodes</p>
        <div className="sb-filters">
          <FilterBtn
            label="All types"
            count={totalNodes}
            active={filterType === 'all'}
            color="var(--c-accent)"
            onClick={() => onFilterChange('all')}
          />
          {nodeTypes.map(t => {
            const meta = NODE_META[t.type] || {};
            return (
              <FilterBtn
                key={t.type}
                label={meta.label || t.type}
                count={t.count}
                active={filterType === t.type}
                color={meta.color || '#888'}
                onClick={() => onFilterChange(t.type)}
              />
            );
          })}
        </div>
      </section>

      <div className="divider" />

      {/* ── KPI cards ── */}
      <section className="sb-section sb-section--grow">
        <p className="section-label">Dataset overview</p>
        <div className="sb-kpis">
          {stats ? (
            <>
              <KpiCard
                label="Total Revenue"
                value={`₹${fmtNum(stats.total_revenue)}`}
                sub={`${stats.total_payments} payments received`}
                variant="green"
              />
              <KpiCard
                label="Sales Orders"
                value={stats.total_sales_orders}
                sub={`${stats.total_customers} unique customers`}
              />
              <KpiCard
                label="No Delivery"
                value={stats.orders_no_delivery}
                sub="orders not yet shipped"
                variant="amber"
              />
              <KpiCard
                label="Unbilled"
                value={stats.delivered_not_billed}
                sub="delivered, not invoiced"
                variant="red"
              />
              <KpiCard
                label="Products"
                value={stats.total_products}
                sub={`${stats.cancelled_billing_docs} cancelled bills`}
              />
            </>
          ) : (
            Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />)
          )}
        </div>
      </section>

    </aside>
  );
}

function FilterBtn({ label, count, active, color, onClick }) {
  return (
    <button
      className={`sb-filter ${active ? 'sb-filter--active' : ''}`}
      style={{ '--fc': color }}
      onClick={onClick}
    >
      <span className="sb-filter__dot" />
      <span className="sb-filter__label">{label}</span>
      <span className="sb-filter__count mono">{count}</span>
    </button>
  );
}

function KpiCard({ label, value, sub, variant }) {
  return (
    <div className={`kpi-card ${variant ? `kpi-card--${variant}` : ''}`}>
      <div className="kpi-card__label section-label">{label}</div>
      <div className="kpi-card__value mono">{value}</div>
      {sub && <div className="kpi-card__sub">{sub}</div>}
    </div>
  );
}

function KpiSkeleton() {
  return (
    <div className="kpi-card">
      <div className="skeleton" style={{ height: 9, width: '55%', marginBottom: 8 }} />
      <div className="skeleton" style={{ height: 22, width: '70%', marginBottom: 5 }} />
      <div className="skeleton" style={{ height: 8, width: '80%' }} />
    </div>
  );
}

function fmtNum(n) {
  if (!n) return '0';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
  return n.toString();
}
