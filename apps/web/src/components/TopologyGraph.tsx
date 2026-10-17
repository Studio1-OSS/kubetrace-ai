import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Box, Layers, Maximize2, Network, Rocket, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { HealthDot } from "@/components/common";
import { cn } from "@/lib/utils";
import type { Topology, TopoNode } from "@/lib/types";

const COLUMN_X: Record<string, number> = { Deployment: 0, ReplicaSet: 260, Pod: 520, Service: 800 };
// Compact: the same flow top to bottom, for a narrow pane. Deployment → ReplicaSet → Pod ← Service.
// Each kind is a band, wrapped at two per row, so the graph stays narrow enough to read at full size.
const BAND_ORDER = ["Deployment", "ReplicaSet", "Pod", "Service"];
const COMPACT_COLS = 2;
const COMPACT_STEP_X = 182;
const COMPACT_STEP_Y = 82;
const BAND_GAP = 34;
const ICON: Record<string, typeof Box> = { Service: Network, Deployment: Rocket, ReplicaSet: Layers, Pod: Box };

function ResourceNode({ data }: NodeProps<Node<{ node: TopoNode; highlighted: boolean; compact: boolean }>>) {
  const { node, highlighted, compact } = data;
  const Icon = ICON[node.kind] ?? Box;
  return (
    <div className={cn("rounded-lg border bg-panel px-3 py-2 shadow-sm transition-colors", compact ? "w-[166px]" : "w-[210px]",
      highlighted ? "border-accent" : node.health === "error" ? "border-bad/50" : node.health === "warn" ? "border-warn/40" : "border-line")}>
      <Handle type="target" position={compact ? Position.Top : Position.Left} className="!size-1.5 !border-0 !bg-line" />
      <div className="flex items-center gap-2">
        <Icon className="size-3.5 text-muted" />
        <span className="text-[10px] uppercase tracking-wide text-faint">{node.kind}</span>
        <HealthDot health={node.health} className="ml-auto" />
      </div>
      <div className="mt-1 truncate font-mono text-[11.5px] text-ink" title={node.name}>{node.name}</div>
      <div className="truncate text-[10.5px] text-muted" title={node.detail}>{node.detail}</div>
      <Handle type="source" position={compact ? Position.Bottom : Position.Right} className="!size-1.5 !border-0 !bg-line" />
    </div>
  );
}

const nodeTypes = { resource: ResourceNode };

export function TopologyGraph({ topology, onSelect, highlight = [], className, compact = false }: {
  topology: Topology | null; onSelect?: (n: TopoNode) => void; highlight?: string[]; className?: string;
  /** Narrow pane: top-to-bottom layout, legend below the graph, and an Expand button for the full view. */
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  const { nodes, edges } = useMemo(() => {
    if (!topology) return { nodes: [] as Node[], edges: [] as Edge[] };
    // Four columns, left to right: Deployment → ReplicaSet → Pod ← Service.
    const counts: Record<string, number> = {};
    const totals: Record<string, number> = {};
    for (const n of topology.nodes) totals[n.kind] = (totals[n.kind] ?? 0) + 1;
    const bandY: Record<string, number> = {};
    let y = 0;
    for (const kind of [...BAND_ORDER, ...Object.keys(totals).filter((k) => !BAND_ORDER.includes(k))]) {
      if (!totals[kind]) continue;
      bandY[kind] = y;
      y += Math.ceil(totals[kind] / COMPACT_COLS) * COMPACT_STEP_Y + BAND_GAP;
    }
    const compactPosition = (kind: string, index: number) => {
      const total = totals[kind] ?? 1;
      const row = Math.floor(index / COMPACT_COLS);
      const inRow = Math.min(COMPACT_COLS, total - row * COMPACT_COLS);
      const col = index % COMPACT_COLS;
      return { x: (col - (inRow - 1) / 2) * COMPACT_STEP_X, y: (bandY[kind] ?? 0) + row * COMPACT_STEP_Y };
    };
    const nodes: Node[] = topology.nodes.map((n) => {
      const index = (counts[n.kind] = (counts[n.kind] ?? 0) + 1) - 1;
      const position = compact ? compactPosition(n.kind, index) : { x: COLUMN_X[n.kind] ?? 0, y: index * 92 };
      return { id: n.id, type: "resource", position, data: { node: n, highlighted: highlight.includes(n.id), compact } };
    });
    const ids = new Set(nodes.map((n) => n.id));
    const edges: Edge[] = topology.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e, i) => ({
      id: `${e.source}-${e.target}-${i}`, source: e.kind === "endpoint" || e.kind === "selects" ? e.target : e.source,
      target: e.kind === "endpoint" || e.kind === "selects" ? e.source : e.target,
      animated: false,
      style: { stroke: e.kind === "endpoint" ? "hsl(152 58% 50%)" : e.observed ? "hsl(220 10% 50%)" : "hsl(38 92% 58%)",
               strokeDasharray: e.observed ? undefined : "5 4", strokeWidth: 1.4 },
      label: e.kind === "owns" ? undefined : e.kind === "endpoint" ? "endpoint" : "selector match (inferred)",
      labelStyle: { fill: "hsl(220 10% 64%)", fontSize: 10 }, labelBgStyle: { fill: "hsl(222 20% 10%)" },
    }));
    return { nodes, edges };
  }, [topology, highlight, compact]);

  const legend = (
    <>
      <div className="flex items-center gap-2"><span className="h-0.5 w-5 bg-ok" /> endpoint (API: EndpointSlice)</div>
      <div className="flex items-center gap-2"><span className="h-0.5 w-5 bg-faint" /> owner (API: ownerReference)</div>
      <div className="flex items-center gap-2"><span className="h-0.5 w-5 border-t border-dashed border-warn" /> selector match only (inferred)</div>
    </>
  );

  return (
    <div className={cn("flex h-full w-full flex-col", className)} data-testid="topology">
      <div className={cn("relative min-h-0 w-full flex-1", compact ? "min-h-[300px]" : "min-h-[320px]")}>
        <ReactFlow key={compact ? "compact" : "full"} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
          fitViewOptions={{ padding: compact ? 0.08 : 0.15 }} minZoom={0.3}
          nodesDraggable={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onSelect?.((n.data as any).node)}>
          <Background color="hsl(222 14% 18%)" gap={22} />
          {!compact && <Controls showInteractive={false} position="bottom-left" />}
        </ReactFlow>
        {!compact && (
          <div className="pointer-events-none absolute right-3 top-3 space-y-1 rounded-md border border-line bg-panel/90 px-2.5 py-2 text-[10.5px] text-muted">
            {legend}
          </div>
        )}
        {topology && topology.nodes.length === 0 && (
          <div className="absolute inset-0 grid place-items-center text-xs text-faint">No workloads in {topology.namespace}.</div>
        )}
      </div>
      {compact && (
        <div className="flex items-start gap-3 border-t border-line px-3 py-2 text-[10.5px] text-muted">
          <div className="flex flex-1 flex-wrap gap-x-4 gap-y-1">{legend}</div>
          <button type="button" onClick={() => setExpanded(true)} data-testid="topology-expand"
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-panel px-2 py-1 text-[11px] text-muted hover:text-ink">
            <Maximize2 className="size-3" /> Expand
          </button>
        </div>
      )}
      {compact && expanded && (
        <div className="fixed inset-0 z-50 flex flex-col bg-bg/95 p-4 backdrop-blur-sm" role="dialog" aria-label="Topology" data-testid="topology-expanded">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">Topology{topology ? ` · ${topology.namespace}` : ""}</span>
            <button type="button" onClick={() => setExpanded(false)} aria-label="Close"
              className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-muted hover:text-ink"><X className="size-3.5" /> Close</button>
          </div>
          <div className="min-h-0 flex-1 rounded-lg border border-line">
            <TopologyGraph topology={topology} highlight={highlight} onSelect={onSelect} />
          </div>
        </div>
      )}
    </div>
  );
}
