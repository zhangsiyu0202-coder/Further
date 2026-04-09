import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { GraphData, GraphStatus } from '../lib/api';

interface NodeDatum extends d3.SimulationNodeDatum {
  id: string;
  group: number;
  label: string;
  kind?: string;
}

interface LinkDatum extends d3.SimulationLinkDatum<NodeDatum> {
  source: string | NodeDatum;
  target: string | NodeDatum;
  value: number;
  relation?: string;
  relation_type?: string;
}

function buildFallbackGraph(data: any): GraphData {
  const nodes = [{ id: 'root', label: data.objective || '预测目标', kind: 'objective' }];
  const edges = [] as Array<{ source: string; target: string; relation: string; value: number }>;

  return { nodes, edges };
}

export default function KnowledgeGraph({
  data,
  graphData,
  graphStatus,
  onRefresh,
  refreshDisabled,
}: {
  data: any;
  graphData: GraphData;
  graphStatus: GraphStatus | null;
  onRefresh?: () => void;
  refreshDisabled?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('');
  const [highlightedNodeId, setHighlightedNodeId] = useState<string>('');
  const sourceGraph =
    graphData.nodes.length > 0 || graphData.edges.length > 0 ? graphData : buildFallbackGraph(data);
  const selectedNode = sourceGraph.nodes.find((node) => node.id === selectedNodeId) || null;
  const selectedRelations = selectedNode
    ? sourceGraph.edges.filter(
        (edge) => String(edge.source) === selectedNode.id || String(edge.target) === selectedNode.id,
      )
    : [];

  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;

    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight;

    d3.select(svgRef.current).selectAll('*').remove();

    const svg = d3
      .select(svgRef.current)
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [0, 0, width, height]);

    const nodes: NodeDatum[] = sourceGraph.nodes.map((node, index) => ({
      id: node.id,
      label: node.label || node.name || node.id,
      kind: node.kind,
      group:
        node.kind === 'objective' ? 1 : node.kind === 'scenario' ? 3 : index === 0 ? 1 : 2,
    }));
    const nodeIds = new Set(nodes.map((node) => node.id));

    const links: LinkDatum[] = sourceGraph.edges
      .filter((edge) => nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target)))
      .map((edge) => ({
        source: edge.source,
        target: edge.target,
        relation: edge.relation || edge.label,
        relation_type: edge.relation_type,
        value: edge.value || 1.5,
      }));

    const simulation = d3
      .forceSimulation<NodeDatum>(nodes)
      .force('link', d3.forceLink<NodeDatum, LinkDatum>(links).id((d) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-320))
      .force('center', d3.forceCenter(width / 2, height / 2));

    const link = svg
      .append('g')
      .attr('stroke', '#d4d4d4')
      .attr('stroke-opacity', 0.8)
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke-width', (d) => Math.sqrt(d.value))
      .attr('stroke', (d) => {
        const sourceId = typeof d.source === 'string' ? d.source : d.source.id;
        const targetId = typeof d.target === 'string' ? d.target : d.target.id;
        if (
          selectedNodeId &&
          (sourceId === selectedNodeId || targetId === selectedNodeId) &&
          (sourceId === highlightedNodeId || targetId === highlightedNodeId)
        ) {
          return '#171717';
        }
        if (selectedNodeId && (sourceId === selectedNodeId || targetId === selectedNodeId)) {
          return '#737373';
        }
        return '#d4d4d4';
      })
      .attr('stroke-opacity', (d) => {
        const sourceId = typeof d.source === 'string' ? d.source : d.source.id;
        const targetId = typeof d.target === 'string' ? d.target : d.target.id;
        if (
          selectedNodeId &&
          (sourceId === selectedNodeId || targetId === selectedNodeId) &&
          (sourceId === highlightedNodeId || targetId === highlightedNodeId)
        ) {
          return 1;
        }
        if (selectedNodeId && (sourceId === selectedNodeId || targetId === selectedNodeId)) {
          return 0.95;
        }
        return 0.35;
      });

    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .call(
        d3
          .drag<SVGGElement, NodeDatum>()
          .on('start', dragstarted)
          .on('drag', dragged)
          .on('end', dragended) as any,
      );

    node
      .append('circle')
      .attr('r', (d) => (d.group === 1 ? 14 : d.group === 2 ? 9 : 7))
      .attr('fill', (d) => {
        if (d.id === highlightedNodeId) return '#0f766e';
        return d.group === 1 ? '#111111' : d.group === 2 ? '#404040' : '#737373';
      })
      .attr('stroke', (d) => {
        if (d.id === selectedNodeId) return '#111111';
        if (d.id === highlightedNodeId) return '#0f766e';
        return '#ffffff';
      })
      .attr('stroke-width', (d) => {
        if (d.id === selectedNodeId) return 3;
        if (d.id === highlightedNodeId) return 4;
        return 1.5;
      })
      .style('cursor', 'pointer')
      .on('click', (_event, d) => {
        setSelectedNodeId(d.id);
        setHighlightedNodeId('');
      });

    node
      .append('text')
      .text((d) => d.label)
      .attr('x', 14)
      .attr('y', 4)
      .style('font-size', '11px')
      .style('font-family', 'sans-serif')
      .style('fill', '#404040')
      .style('stroke', 'none');

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    function dragstarted(event: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event: any) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event: any) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return () => simulation.stop();
  }, [data, graphData, highlightedNodeId, selectedNodeId]);

  return (
    <div ref={containerRef} className="w-full h-full bg-neutral-50 relative overflow-hidden">
      <svg ref={svgRef} className="w-full h-full" />
      <div className="absolute top-4 left-4 bg-white/85 backdrop-blur-sm border border-neutral-200 px-3 py-1.5 rounded-full text-[10px] font-medium text-neutral-500 uppercase tracking-wider shadow-sm">
        {graphStatus ? `后端图谱 ${graphStatus.node_count} 节点 / ${graphStatus.edge_count} 连边` : '本地图谱预览'}
      </div>
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10">
        <button
          type="button"
          onClick={onRefresh}
          disabled={!onRefresh || refreshDisabled}
          className="bg-white/90 backdrop-blur-sm border border-neutral-200 px-3 py-1.5 rounded-full text-[11px] font-medium text-neutral-600 hover:text-black transition-colors shadow-sm disabled:opacity-50"
        >
          {refreshDisabled ? '刷新中...' : '刷新图谱'}
        </button>
      </div>
      <div className="absolute right-4 bottom-4 w-[320px] max-w-[80%] bg-white/92 backdrop-blur-sm border border-neutral-200 px-4 py-4 rounded-2xl shadow-sm">
        {selectedNode ? (
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-400">图谱详情</div>
                <div className="text-base font-semibold text-neutral-900 mt-1">{selectedNode.label || selectedNode.name || selectedNode.id}</div>
              </div>
              <button
                onClick={() => {
                  setSelectedNodeId('');
                  setHighlightedNodeId('');
                }}
                className="text-xs text-neutral-500 hover:text-black transition-colors"
              >
                关闭
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="px-2.5 py-1 rounded-full bg-neutral-900 text-xs text-white">
                {selectedNode.kind || '实体'}
              </span>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-neutral-400 mb-1">摘要</div>
              <div className="text-sm text-neutral-700 leading-6">
                {selectedNode.summary || '这个节点目前还没有摘要信息。'}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-neutral-400 mb-2">关联关系</div>
              <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
                {selectedRelations.length ? selectedRelations.slice(0, 8).map((edge) => {
                  const outgoing = String(edge.source) === selectedNode.id;
                  const otherNodeId = outgoing ? String(edge.target) : String(edge.source);
                  const otherNode = sourceGraph.nodes.find((node) => node.id === otherNodeId);
                  const isHighlighted = highlightedNodeId === otherNodeId;
                  return (
                    <button
                      type="button"
                      key={edge.id || `${edge.source}-${edge.target}-${edge.relation}`}
                      onClick={() => setHighlightedNodeId(otherNodeId)}
                      className={`w-full text-left rounded-xl px-3 py-2 transition-colors ${
                        isHighlighted
                          ? 'bg-teal-50 border-teal-200'
                          : 'bg-neutral-50 border-neutral-100 hover:border-neutral-200 hover:bg-neutral-100/80'
                      } border`}
                    >
                      <div className="text-xs font-medium text-neutral-800">
                        {outgoing ? '指向' : '来自'} {otherNode?.label || otherNode?.name || '未知节点'}
                      </div>
                      <div className="text-xs text-neutral-500 mt-1">
                        {(edge.relation_type || edge.relation || '关联').toString()}
                      </div>
                      {edge.relation ? (
                        <div className="text-xs text-neutral-600 mt-1 line-clamp-2">{edge.relation}</div>
                      ) : null}
                    </button>
                  );
                }) : (
                  <div className="text-sm text-neutral-500">这个节点当前没有可展示的关系。</div>
                )}
              </div>
            </div>
          </div>
        ) : (
            <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-400">图谱详情</div>
            <div className="text-sm text-neutral-600 leading-6">
              点击图中的任意节点，查看它的类型、摘要和关联关系。
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
