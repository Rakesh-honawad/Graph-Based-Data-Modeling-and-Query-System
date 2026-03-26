import React, { useRef, useState, useEffect, useCallback } from 'react';
import { useGraph } from '../../hooks/useGraph';
import NodeDetail from './NodeDetail';
import './GraphPanel.css';

export default function GraphPanel({
  graphData,
  filterType,
  highlightedNodes,
  isLoading,
  onExpandNode,
  onTraceFlow,
}) {
  const svgRef        = useRef(null);
  const [selected, setSelected] = useState(null);

  const handleClick    = useCallback((d) => {
    if (!d) { setSelected(null); return; }
    // Count connections from graphData
    const edges     = graphData?.edges || [];
    const connCount = edges.filter(e => {
      const s = e.source?.id ?? e.source;
      const t = e.target?.id ?? e.target;
      return s === d.id || t === d.id;
    }).length;
    setSelected({ ...d, connections: connCount });
  }, [graphData]);

  const handleDblClick = useCallback((id) => onExpandNode?.(id), [onExpandNode]);

  const { render, highlight, zoomIn, zoomOut, zoomReset, zoomFit } = useGraph({
    svgRef,
    onNodeClick:    handleClick,
    onNodeDblClick: handleDblClick,
  });

  useEffect(() => {
    if (graphData?.nodes?.length) render(graphData, filterType);
  }, [graphData, filterType, render]);

  useEffect(() => {
    highlight(Array.from(highlightedNodes || []));
  }, [highlightedNodes, highlight]);

  useEffect(() => {
    if (!isLoading && graphData?.nodes?.length) {
      const t = setTimeout(() => zoomFit(), 700);
      return () => clearTimeout(t);
    }
  }, [isLoading, graphData, zoomFit]);

  const nodeCount = graphData?.nodes?.length || 0;
  const edgeCount = graphData?.edges?.length || 0;

  return (
    <div className="graph-panel">
      <svg ref={svgRef} className="graph-svg" />

      {/* Loading */}
      {isLoading && (
        <div className="graph-overlay">
          <div className="spinner spinner--lg" />
          <span className="graph-overlay__text">Building graph…</span>
        </div>
      )}

      {/* Empty */}
      {!isLoading && !nodeCount && (
        <div className="graph-overlay graph-overlay--empty">
          <div className="graph-overlay__icon">
            <svg viewBox="0 0 48 48" fill="none">
              <circle cx="14" cy="24" r="6" stroke="currentColor" strokeWidth="1.5"/>
              <circle cx="34" cy="14" r="6" stroke="currentColor" strokeWidth="1.5"/>
              <circle cx="34" cy="34" r="6" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M20 22l8-6M20 26l8 6" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
          </div>
          <p className="graph-overlay__title">Cannot reach backend</p>
          <p className="graph-overlay__sub">Start the API on port 8000, then refresh</p>
        </div>
      )}

      {/* Node detail panel */}
      {selected && (
        <NodeDetail
          node={selected}
          onClose={() => setSelected(null)}
          onExpand={() => { onExpandNode?.(selected.id); setSelected(null); }}
          onTrace={() => { onTraceFlow?.(selected.id, selected.label); setSelected(null); }}
        />
      )}

      {/* Zoom toolbar */}
      <div className="graph-toolbar">
        <button className="icon-btn" onClick={zoomIn}    title="Zoom in">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/>
          </svg>
        </button>
        <button className="icon-btn" onClick={zoomOut}   title="Zoom out">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M8 11h6"/>
          </svg>
        </button>
        <button className="icon-btn" onClick={zoomFit}   title="Fit all nodes">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
          </svg>
        </button>
        <button className="icon-btn" onClick={zoomReset} title="Reset zoom">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
        </button>
      </div>

      {/* Node/edge badge */}
      {nodeCount > 0 && (
        <div className="graph-badge">
          <span className="mono">{nodeCount}</span> nodes
          <span className="graph-badge__sep"/>
          <span className="mono">{edgeCount}</span> edges
          {highlightedNodes?.size > 0 && (
            <><span className="graph-badge__sep"/>
              <span className="graph-badge__hl mono">{highlightedNodes.size} highlighted</span>
            </>
          )}
        </div>
      )}

      {/* Legend strip */}
      <div className="graph-legend">
        <span className="section-label" style={{ marginRight: 10, flexShrink: 0 }}>Legend</span>
        {[
          ['SalesOrder','#4267B8'], ['Delivery','#2D7D52'], ['BillingDoc','#B86E1A'],
          ['Payment','#7B4BAD'], ['JournalEntry','#C0404A'],
          ['Customer','#1E7D9B'], ['Product','#4D8B7A'], ['Plant','#8B6B3D'],
        ].map(([label, color]) => (
          <div key={label} className="legend-item">
            <span className="legend-dot" style={{ background: color }}/>
            <span>{label}</span>
          </div>
        ))}
        <span className="graph-hint">Click node to inspect · Double-click to expand</span>
      </div>
    </div>
  );
}
