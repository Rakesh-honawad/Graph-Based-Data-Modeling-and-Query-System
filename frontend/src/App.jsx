import React, { useState, useEffect, useCallback, useRef } from 'react';
import TopBar   from './components/Layout/TopBar';
import Sidebar  from './components/Sidebar/Sidebar';
import GraphPanel from './components/Graph/GraphPanel';
import ChatPanel  from './components/Chat/ChatPanel';
import { graphApi, analyticsApi } from './utils/api';
import './styles/tokens.css';
import './styles/utils.css';
import './App.css';

export default function App() {
  const [stats,     setStats]     = useState(null);
  const [nodeTypes, setNodeTypes] = useState([]);
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [filter,    setFilter]    = useState('all');
  const [highlighted, setHighlighted] = useState(new Set());
  const [loading,   setLoading]   = useState(true);
  const [connected, setConnected] = useState(true);

  /* ── Load overview graph ── */
  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const data = await graphApi.overview();
      setGraphData(data);
      setConnected(true);
    } catch {
      setGraphData({ nodes: [], edges: [] });
      setConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  /* ── Expand a node's neighbourhood ── */
  const expandNode = useCallback(async (nodeId) => {
    setLoading(true);
    try {
      const data = await graphApi.subgraph(nodeId, 2);
      setGraphData(data);
      setHighlighted(new Set([nodeId]));
    } catch (err) {
      console.error('Expand failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  /* ── Trace full O2C flow ── */
  const traceFlow = useCallback(async (nodeId) => {
    setLoading(true);
    try {
      const data = await graphApi.flow(nodeId);
      if (data?.nodes?.length) {
        setGraphData(data);
        setHighlighted(new Set([nodeId]));
      }
    } catch (err) {
      console.error('Trace failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  /* ── Reset ── */
  const handleReset = useCallback(() => {
    setFilter('all');
    setHighlighted(new Set());
    loadOverview();
  }, [loadOverview]);

  /* ── Init ── */
  useEffect(() => {
    loadOverview();
    analyticsApi.summary().then(setStats).catch(() => {});
    graphApi.nodeTypes().then(setNodeTypes).catch(() => {});
  }, [loadOverview]);

  return (
    <div className="app">
      <TopBar
        stats={stats}
        onReset={handleReset}
        connected={connected}
      />
      <div className="app-body">
        <Sidebar
          stats={stats}
          nodeTypes={nodeTypes}
          filterType={filter}
          onFilterChange={setFilter}
          onExpandNode={expandNode}
        />
        <GraphPanel
          graphData={graphData}
          filterType={filter}
          highlightedNodes={highlighted}
          isLoading={loading}
          onExpandNode={expandNode}
          onTraceFlow={traceFlow}
        />
        <ChatPanel
          onHighlight={setHighlighted}
          onExpandNode={expandNode}
        />
      </div>
    </div>
  );
}
