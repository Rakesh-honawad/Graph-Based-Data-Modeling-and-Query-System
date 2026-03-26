import { useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import { getNodeColor, getNodeSize } from '../utils/graphConstants';

/**
 * useGraph — D3 force simulation hook.
 *
 * Key behaviours:
 *  - Click node → highlights that node + ALL its directly connected edges
 *    and neighbour nodes (like the reference image — selected branch glows)
 *  - Double-click → expand subgraph
 *  - Deselect → click empty canvas
 *  - highlight(ids) → external highlight from chat results
 */
export function useGraph({ svgRef, onNodeClick, onNodeDblClick }) {
  const simRef  = useRef(null);
  const zoomRef = useRef(null);
  const gRef    = useRef(null);
  // Store current node/edge selections so we can update highlights without re-render
  const nodeSelRef = useRef(null);
  const linkSelRef = useRef(null);
  const nodesDataRef = useRef([]);

  // ── Init ─────────────────────────────────────────────────────────────────
  const init = useCallback(() => {
    const el = svgRef.current;
    if (!el) return;

    const sel = d3.select(el);
    sel.selectAll('*').remove();

    const defs = sel.append('defs');

    // Dot-grid background
    const pat = defs.append('pattern')
      .attr('id', 'g-dots').attr('width', 28).attr('height', 28)
      .attr('patternUnits', 'userSpaceOnUse');
    pat.append('circle').attr('cx', 14).attr('cy', 14).attr('r', .9)
      .attr('fill', '#CCC8C0');

    sel.append('rect').attr('width','100%').attr('height','100%')
      .attr('fill','url(#g-dots)');

    // Arrow markers
    ['SalesOrder','Delivery','BillingDoc','Payment','JournalEntry',
     'Customer','Product','Plant'].forEach(type => {
      defs.append('marker')
        .attr('id', `arr-${type}`)
        .attr('viewBox', '0 -4 8 8')
        .attr('refX', 24).attr('refY', 0)
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,-4L8,0L0,4')
        .attr('fill', getNodeColor(type)).attr('opacity', .55);
    });

    // Default marker (grey)
    defs.append('marker').attr('id','arr-default')
      .attr('viewBox','0 -4 8 8').attr('refX',24).attr('refY',0)
      .attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
      .append('path').attr('d','M0,-4L8,0L0,4').attr('fill','#999');

    const zoom = d3.zoom().scaleExtent([0.05, 8])
      .on('zoom', e => { if (gRef.current) gRef.current.attr('transform', e.transform); });
    zoomRef.current = zoom;
    sel.call(zoom);

    gRef.current = sel.append('g').attr('class', 'root');
  }, [svgRef]);

  // ── Render ────────────────────────────────────────────────────────────────
  const render = useCallback((rawData, filter = 'all') => {
    if (!gRef.current || !svgRef.current) return;
    if (!rawData?.nodes?.length) return;

    if (simRef.current) simRef.current.stop();
    const g = gRef.current;
    g.selectAll('*').remove();

    const nodes = (filter === 'all'
      ? rawData.nodes : rawData.nodes.filter(n => n.type === filter)
    ).map(n => ({ ...n }));

    const idSet = new Set(nodes.map(n => n.id));
    const edges = (rawData.edges || [])
      .filter(e => idSet.has(e.source?.id ?? e.source) && idSet.has(e.target?.id ?? e.target))
      .map(e => ({ ...e }));

    nodesDataRef.current = nodes;

    const { width, height } = svgRef.current.getBoundingClientRect();

    const sim = d3.forceSimulation(nodes)
      .force('link',    d3.forceLink(edges).id(d => d.id).distance(90).strength(0.45))
      .force('charge',  d3.forceManyBody().strength(-300))
      .force('center',  d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(d => getNodeSize(d.type) + 12))
      .force('x',       d3.forceX(width  / 2).strength(0.04))
      .force('y',       d3.forceY(height / 2).strength(0.04));

    simRef.current = sim;

    // ── Edge layer ──────────────────────────────────────────────────────────
    const linkG  = g.append('g').attr('class', 'edges');
    const linkSel = linkG.selectAll('line').data(edges).join('line')
      .attr('class', 'edge')
      .attr('stroke', d => {
        const srcId = d.source?.id ?? d.source;
        const src   = nodes.find(n => n.id === srcId);
        return src ? getNodeColor(src.type) + '40' : '#C8C0B440';
      })
      .attr('stroke-width', 1.2)
      .attr('marker-end', d => {
        const srcId = d.source?.id ?? d.source;
        const src   = nodes.find(n => n.id === srcId);
        return `url(#arr-${src?.type ?? 'default'})`;
      });

    linkSelRef.current = linkSel;

    // ── Node layer ──────────────────────────────────────────────────────────
    const nodeG   = g.append('g').attr('class', 'nodes');
    const nodeSel = nodeG.selectAll('g').data(nodes).join('g')
      .attr('class', 'node-g')
      .style('cursor', 'pointer')
      .call(
        d3.drag()
          .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on('end',   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      )
      .on('click',    (e, d) => { e.stopPropagation(); _selectNode(d, edges); onNodeClick?.(d); })
      .on('dblclick', (e, d) => { e.stopPropagation(); onNodeDblClick?.(d.id); });

    nodeSelRef.current = nodeSel;

    // Outer glow ring (selection / highlight)
    nodeSel.append('circle').attr('class', 'node-ring')
      .attr('r', d => getNodeSize(d.type) + 8)
      .attr('fill', 'none')
      .attr('stroke', d => getNodeColor(d.type))
      .attr('stroke-width', 2.5)
      .attr('opacity', 0);

    // White backing
    nodeSel.append('circle').attr('class', 'node-bg')
      .attr('r', d => getNodeSize(d.type) + 3)
      .attr('fill', '#FAFAF8')
      .attr('stroke', d => getNodeColor(d.type))
      .attr('stroke-width', 1);

    // Main fill circle
    nodeSel.append('circle').attr('class', 'node-fill')
      .attr('r', d => getNodeSize(d.type))
      .attr('fill', d => getNodeColor(d.type))
      .attr('fill-opacity', 0.2)
      .attr('stroke', d => getNodeColor(d.type))
      .attr('stroke-width', 1.8);

    // Centre dot
    nodeSel.append('circle').attr('class', 'node-dot')
      .attr('r', d => Math.max(2.5, getNodeSize(d.type) * 0.3))
      .attr('fill', d => getNodeColor(d.type))
      .attr('fill-opacity', 0.75);

    // Labels for anchor types
    nodeSel.filter(d => ['Customer','Plant'].includes(d.type))
      .append('text')
      .attr('class', 'node-label')
      .attr('dy', d => getNodeSize(d.type) + 14)
      .attr('text-anchor', 'middle')
      .attr('font-family', "'DM Mono', monospace")
      .attr('font-size', '9px')
      .attr('fill', d => getNodeColor(d.type))
      .attr('fill-opacity', 0.7)
      .attr('pointer-events', 'none')
      .text(d => (d.label || '').slice(0, 18));

    // Hover
    nodeSel
      .on('mouseenter', function(e, d) {
        d3.select(this).select('.node-fill').attr('fill-opacity', .4);
        d3.select(this).select('.node-ring').attr('opacity', .3);
      })
      .on('mouseleave', function(e, d) {
        // restore unless selected
        const isSelected = d3.select(this).classed('selected');
        if (!isSelected) {
          d3.select(this).select('.node-fill').attr('fill-opacity', .2);
          d3.select(this).select('.node-ring').attr('opacity', 0);
        }
      });

    // Tick
    sim.on('tick', () => {
      linkSel
        .attr('x1', d => d.source.x ?? 0).attr('y1', d => d.source.y ?? 0)
        .attr('x2', d => d.target.x ?? 0).attr('y2', d => d.target.y ?? 0);
      nodeSel.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Deselect on canvas click
    d3.select(svgRef.current).on('click', () => {
      _clearSelection();
      onNodeClick?.(null);
    });

  }, [svgRef, onNodeClick, onNodeDblClick]);

  // ── Internal: select a node + highlight its branch ────────────────────────
  const _selectNode = useCallback((d, edges) => {
    if (!nodeSelRef.current || !linkSelRef.current) return;

    // Find all edge indices connected to this node
    const connectedNodeIds = new Set([d.id]);
    const connectedEdgeIds = new Set();

    linkSelRef.current.each((e, i) => {
      const srcId = e.source?.id ?? e.source;
      const tgtId = e.target?.id ?? e.target;
      if (srcId === d.id || tgtId === d.id) {
        connectedEdgeIds.add(i);
        connectedNodeIds.add(srcId);
        connectedNodeIds.add(tgtId);
      }
    });

    // Dim everything first
    linkSelRef.current
      .attr('stroke-opacity', 0.12)
      .attr('stroke-width', 1);

    nodeSelRef.current.classed('selected', false);
    nodeSelRef.current.select('.node-fill').attr('fill-opacity', 0.08);
    nodeSelRef.current.select('.node-ring').attr('opacity', 0);
    nodeSelRef.current.select('.node-bg').attr('fill-opacity', 0.4);

    // Highlight connected edges — bright + thick
    linkSelRef.current
      .filter((e, i) => connectedEdgeIds.has(i))
      .attr('stroke', e => {
        const srcId = e.source?.id ?? e.source;
        const src   = nodesDataRef.current.find(n => n.id === srcId);
        return src ? getNodeColor(src.type) : '#888';
      })
      .attr('stroke-opacity', 0.85)
      .attr('stroke-width', 2.2);

    // Highlight connected nodes
    nodeSelRef.current
      .filter(n => connectedNodeIds.has(n.id))
      .each(function(n) {
        const sel = d3.select(this);
        sel.select('.node-fill').attr('fill-opacity', n.id === d.id ? 0.55 : 0.3);
        sel.select('.node-ring').attr('opacity', n.id === d.id ? 0.8 : 0.4);
        sel.select('.node-bg').attr('fill-opacity', 1);
      });

    // Mark selected
    nodeSelRef.current.filter(n => n.id === d.id).classed('selected', true);

  }, []);

  const _clearSelection = useCallback(() => {
    if (!nodeSelRef.current || !linkSelRef.current) return;
    nodeSelRef.current.classed('selected', false);
    nodeSelRef.current.select('.node-fill').attr('fill-opacity', 0.2);
    nodeSelRef.current.select('.node-ring').attr('opacity', 0);
    nodeSelRef.current.select('.node-bg').attr('fill-opacity', 1);
    linkSelRef.current
      .attr('stroke', d => {
        const srcId = d.source?.id ?? d.source;
        const src   = nodesDataRef.current.find(n => n.id === srcId);
        return src ? getNodeColor(src.type) + '40' : '#C8C0B440';
      })
      .attr('stroke-opacity', 1)
      .attr('stroke-width', 1.2);
  }, []);

  // ── External highlight from chat (highlights node + its ring) ─────────────
  const highlight = useCallback((ids) => {
    if (!nodeSelRef.current) return;
    const idSet = new Set(ids);
    nodeSelRef.current.each(function(d) {
      const lit = idSet.has(d.id);
      d3.select(this).select('.node-ring').attr('opacity', lit ? 0.7 : 0);
      d3.select(this).select('.node-fill').attr('fill-opacity', lit ? 0.45 : 0.2);
    });
  }, []);

  // ── Zoom helpers ──────────────────────────────────────────────────────────
  const zoomIn    = useCallback(() => {
    if (zoomRef.current && svgRef.current)
      d3.select(svgRef.current).transition().duration(300)
        .call(zoomRef.current.scaleBy, 1.4);
  }, [svgRef]);

  const zoomOut   = useCallback(() => {
    if (zoomRef.current && svgRef.current)
      d3.select(svgRef.current).transition().duration(300)
        .call(zoomRef.current.scaleBy, 0.72);
  }, [svgRef]);

  const zoomReset = useCallback(() => {
    if (zoomRef.current && svgRef.current)
      d3.select(svgRef.current).transition().duration(400)
        .call(zoomRef.current.transform, d3.zoomIdentity);
  }, [svgRef]);

  const zoomFit = useCallback(() => {
    if (!gRef.current || !svgRef.current || !zoomRef.current) return;
    const bounds  = gRef.current.node().getBBox();
    const { width, height } = svgRef.current.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const scale = Math.min(width / bounds.width, height / bounds.height) * 0.82;
    const tx    = width  / 2 - scale * (bounds.x + bounds.width  / 2);
    const ty    = height / 2 - scale * (bounds.y + bounds.height / 2);
    d3.select(svgRef.current).transition().duration(500)
      .call(zoomRef.current.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }, [svgRef]);

  useEffect(() => {
    init();
    return () => simRef.current?.stop();
  }, [init]);

  return { render, highlight, zoomIn, zoomOut, zoomReset, zoomFit };
}
