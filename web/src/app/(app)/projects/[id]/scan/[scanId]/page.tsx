"use client";

import { useParams } from "next/navigation";
import { useQuery } from "convex/react";
import { api } from "../../../../../../../convex/_generated/api";
import { Id } from "../../../../../../../convex/_generated/dataModel";
import { Badge } from "@/components/ui/badge";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useEffect, useRef, useState } from "react";
import {
  ChevronRight,
  FileText,
  Search,
  Brain,
  Eye,
  Send,
  ArrowDown,
  Shield,
  AlertTriangle,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";

// --- Severity config ---
const SEVERITY_CONFIG: Record<
  string,
  { color: string; bg: string; border: string; icon: typeof Shield }
> = {
  critical: {
    color: "text-red-500 dark:text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    icon: AlertTriangle,
  },
  high: {
    color: "text-orange-600 dark:text-orange-400",
    bg: "bg-orange-500/10",
    border: "border-orange-500/20",
    icon: AlertTriangle,
  },
  medium: {
    color: "text-yellow-600 dark:text-yellow-400",
    bg: "bg-yellow-500/10",
    border: "border-yellow-500/20",
    icon: Shield,
  },
  low: {
    color: "text-blue-600 dark:text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-blue-500/20",
    icon: Info,
  },
  info: {
    color: "text-zinc-500 dark:text-zinc-400",
    bg: "bg-zinc-500/5",
    border: "border-zinc-500/20",
    icon: Info,
  },
};

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  queued: { color: "text-yellow-600 dark:text-yellow-400", label: "queued" },
  running: { color: "text-blue-600 dark:text-blue-400", label: "running" },
  completed: { color: "text-emerald-600 dark:text-emerald-400", label: "completed" },
  failed: { color: "text-red-600 dark:text-red-400", label: "failed" },
};

// --- JSON display ---
function JsonBlock({ data }: { data: unknown }) {
  if (data === null || data === undefined) return null;
  const formatted = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="text-xs font-mono bg-muted/50 border border-border rounded px-3 py-2 whitespace-pre-wrap overflow-x-auto text-foreground/70 leading-relaxed">
      {formatted}
    </pre>
  );
}

// --- Action rendering ---
type ActionPayload = string | Record<string, unknown>;

function ActionItem({
  action,
}: {
  action: {
    _id: string;
    type: string;
    payload: ActionPayload;
    timestamp: number;
  };
}) {
  const [expanded, setExpanded] = useState(false);
  const payload = action.payload;
  const isObject = typeof payload === "object" && payload !== null;

  const time = new Date(action.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  if (action.type === "reasoning") {
    return (
      <div className="px-4 py-3 border-l-2 border-purple-500/50 bg-purple-500/5 rounded-r mx-2 my-1">
        <div className="flex items-start gap-2.5">
          <Brain className="h-4 w-4 text-purple-500 dark:text-purple-400 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-foreground/90 whitespace-pre-wrap leading-relaxed">
              {typeof payload === "string" ? payload : JSON.stringify(payload)}
            </p>
            <span className="text-xs text-muted-foreground mt-1.5 block font-mono">
              {time}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (action.type === "observation") {
    return (
      <div className="px-4 py-2 flex items-center gap-2.5 mx-2">
        <Eye className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="text-sm text-muted-foreground">
          {typeof payload === "string" ? payload : JSON.stringify(payload)}
        </span>
        <span className="text-xs text-muted-foreground/60 ml-auto shrink-0 font-mono">
          {time}
        </span>
      </div>
    );
  }

  if (action.type === "tool_call") {
    const tool = isObject ? String((payload as Record<string, unknown>).tool) : "?";
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const input = isObject ? (payload as Record<string, unknown>).input : null;
    const ToolIcon = tool === "read_file" ? FileText : tool === "search_code" ? Search : Send;

    return (
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CollapsibleTrigger asChild>
          <button className="w-full text-left px-4 py-2 flex items-center gap-2.5 hover:bg-accent/50 rounded mx-2 transition-colors cursor-pointer">
            <ChevronRight
              className={`h-3.5 w-3.5 text-muted-foreground transition-transform shrink-0 ${expanded ? "rotate-90" : ""}`}
            />
            <ToolIcon className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400 shrink-0" />
            <Badge
              variant="outline"
              className="text-xs px-2 py-0.5 font-mono border-blue-500/30 text-blue-700 dark:text-blue-300"
            >
              {tool}
            </Badge>
            <span className="text-sm text-foreground/80 truncate flex-1">
              {summary ? String(summary) : ""}
            </span>
            <span className="text-xs text-muted-foreground/60 shrink-0 font-mono">
              {time}
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="ml-14 mr-4 mb-2">
            {input != null && <JsonBlock data={input} />}
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  }

  if (action.type === "tool_result") {
    const tool = isObject ? String((payload as Record<string, unknown>).tool) : "?";
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const ToolIcon = tool === "read_file" ? FileText : tool === "search_code" ? Search : Send;

    return (
      <div className="px-4 py-1.5 flex items-center gap-2.5 mx-2">
        <div className="w-3.5" /> {/* spacer to align with tool_call chevron */}
        <ToolIcon className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
        <span className="text-sm text-muted-foreground">
          {summary
            ? String(summary)
            : typeof payload === "string"
              ? payload
              : JSON.stringify(payload)}
        </span>
        <span className="text-xs text-muted-foreground/60 ml-auto shrink-0 font-mono">
          {time}
        </span>
      </div>
    );
  }

  // Fallback for report type or unknown
  return (
    <div className="px-4 py-2 flex items-center gap-2.5 mx-2">
      <Send className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
      <span className="text-sm text-foreground/80">
        {typeof payload === "string" ? payload : JSON.stringify(payload)}
      </span>
      <span className="text-xs text-muted-foreground/60 ml-auto shrink-0 font-mono">
        {time}
      </span>
    </div>
  );
}

// --- Report panel ---
function ReportPanel({
  report,
}: {
  report: {
    summary?: string;
    findings: Array<{
      title: string;
      severity: string;
      description: string;
      location?: string;
      recommendation?: string;
    }>;
  };
}) {
  const severityCounts = report.findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Report</h2>
          <span className="text-xs text-muted-foreground font-mono">
            {report.findings.length} findings
          </span>
        </div>

        {/* Severity bar */}
        <div className="flex gap-2 mt-2 flex-wrap">
          {(["critical", "high", "medium", "low", "info"] as const).map((sev) => {
            const count = severityCounts[sev] || 0;
            if (count === 0) return null;
            const cfg = SEVERITY_CONFIG[sev];
            return (
              <span
                key={sev}
                className={`text-xs font-mono px-2 py-0.5 rounded ${cfg.bg} ${cfg.color} ${cfg.border} border`}
              >
                {count} {sev}
              </span>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-3">
          {report.summary && (
            <p className="text-sm text-muted-foreground leading-relaxed pb-3 border-b border-border">
              {report.summary}
            </p>
          )}

          {report.findings.map((finding, i) => {
            const cfg = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.info;
            const SevIcon = cfg.icon;
            return (
              <div
                key={i}
                className={`rounded-lg border ${cfg.border} ${cfg.bg} p-4 space-y-2`}
              >
                <div className="flex items-start gap-2.5">
                  <SevIcon className={`h-4 w-4 mt-0.5 shrink-0 ${cfg.color}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">
                        {finding.title}
                      </span>
                      <span className={`text-xs font-mono shrink-0 ${cfg.color}`}>
                        {finding.severity}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                      {finding.description}
                    </p>
                    {finding.location && (
                      <p className="text-xs font-mono text-muted-foreground mt-2 bg-muted px-2 py-1 rounded inline-block">
                        {finding.location}
                      </p>
                    )}
                    {finding.recommendation && (
                      <p className="text-sm text-muted-foreground mt-2 pl-3 border-l-2 border-border">
                        {finding.recommendation}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// --- Trace panel ---
function TracePanel({
  actions,
  isRunning,
}: {
  actions:
    | Array<{
        _id: string;
        type: string;
        payload: ActionPayload;
        timestamp: number;
      }>
    | undefined;
  isRunning: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  };

  useEffect(() => {
    if (autoScroll) {
      scrollToBottom();
    }
  }, [actions?.length, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 60;
    setAutoScroll(isAtBottom);
    setShowScrollButton(!isAtBottom);
  };

  return (
    <div className="h-full flex flex-col relative">
      <div className="px-4 py-3 border-b border-border shrink-0 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Trace</h2>
        <span className="text-xs text-muted-foreground font-mono">
          {actions?.length ?? 0} actions
        </span>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        <div className="py-2 space-y-0.5">
          {(!actions || actions.length === 0) && (
            <div className="flex items-center justify-center py-16">
              <p className="text-sm text-muted-foreground">
                Waiting for agent...
              </p>
            </div>
          )}

          {actions?.map((action) => (
            <ActionItem key={action._id} action={action} />
          ))}

          {isRunning && actions && actions.length > 0 && (
            <div className="flex items-center gap-2.5 px-4 py-3 mx-2 text-sm text-muted-foreground">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
              </span>
              Agent is working...
            </div>
          )}
        </div>
      </div>

      {showScrollButton && (
        <Button
          size="sm"
          variant="outline"
          className="absolute bottom-3 right-3 h-8 w-8 p-0 rounded-full"
          onClick={() => {
            setAutoScroll(true);
            scrollToBottom();
          }}
        >
          <ArrowDown className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

// --- Main page ---
export default function ScanPage() {
  const { id, scanId } = useParams<{ id: string; scanId: string }>();
  const scan = useQuery(api.scans.get, {
    scanId: scanId as Id<"scans">,
  });
  const actions = useQuery(api.actions.listByScan, {
    scanId: scanId as Id<"scans">,
  });
  const report = useQuery(api.reports.getByScan, {
    scanId: scanId as Id<"scans">,
  });

  if (!scan) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <p className="text-sm text-muted-foreground font-mono">
          Loading scan...
        </p>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[scan.status] || STATUS_CONFIG.queued;
  const isRunning = scan.status === "running" || scan.status === "queued";
  const hasReport = !!report;

  return (
    <div className="flex flex-col h-[calc(100vh-4.5rem)]">
      {/* Header */}
      <div className="flex items-center gap-3 pb-3 shrink-0">
        <h1 className="text-base font-semibold tracking-tight">Scan</h1>
        <Badge variant="outline" className="text-xs px-2 py-0.5 font-mono">
          {scan.agent}
        </Badge>
        <span className={`text-xs font-mono flex items-center gap-1.5 ${statusCfg.color}`}>
          {isRunning && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
          )}
          {statusCfg.label}
        </span>
        <span className="text-xs text-muted-foreground font-mono ml-auto">
          {new Date(scan.startedAt).toLocaleString()}
        </span>
      </div>

      {/* Content — both panels scroll independently */}
      <div className="flex-1 min-h-0 border border-border rounded-lg overflow-hidden">
        {hasReport ? (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize={45} minSize={20}>
              <TracePanel actions={actions} isRunning={isRunning} />
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={55} minSize={25}>
              <ReportPanel report={report} />
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          <TracePanel actions={actions} isRunning={isRunning} />
        )}
      </div>
    </div>
  );
}
