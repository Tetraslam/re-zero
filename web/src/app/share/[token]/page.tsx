"use client";

import { useParams } from "next/navigation";
import { useQuery } from "convex/react";
import { api } from "../../../../convex/_generated/api";
import { Id } from "../../../../convex/_generated/dataModel";
import Link from "next/link";
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
import { useEffect, useMemo, useRef, useState } from "react";

// --- Types ---
type ActionPayload = string | Record<string, unknown>;
type Action = {
  _id: string;
  type: string;
  payload: ActionPayload;
  timestamp: number;
};

type Turn = {
  index: number;
  reasoning: string;
  actions: Action[];
  timestamp: number;
};

// --- Spinner ---
const SPINNER_FRAMES = ["|", "/", "\u2014", "\\"];

function RemSpinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 120);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="inline-block w-3 text-center text-rem tabular-nums">
      {SPINNER_FRAMES[frame]}
    </span>
  );
}

function BlinkingCursor() {
  return <span className="inline-block w-1.5 h-3.5 bg-rem animate-blink" />;
}

// --- Screenshot from Convex file storage ---
function ScreenshotImage({ storageId }: { storageId: string }) {
  const url = useQuery(api.storage.getUrl, {
    storageId: storageId as Id<"_storage">,
  });

  if (!url) {
    return (
      <div className="ml-8 mr-2 mb-2 mt-1 h-32 border border-border bg-muted/30 flex items-center justify-center">
        <span className="text-xs text-muted-foreground/40">loading screenshot...</span>
      </div>
    );
  }

  return (
    <div className="ml-8 mr-2 mb-2 mt-1">
      <img
        src={url}
        alt="Screenshot"
        className="border border-border max-w-full max-h-80 object-contain"
      />
    </div>
  );
}

// --- Group actions into turns ---
function groupIntoTurns(actions: Action[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  for (const action of actions) {
    if (action.type === "reasoning") {
      if (current) turns.push(current);
      current = {
        index: turns.length + 1,
        reasoning: typeof action.payload === "string" ? action.payload : "",
        actions: [],
        timestamp: action.timestamp,
      };
    } else {
      if (!current) {
        current = { index: 1, reasoning: "", actions: [], timestamp: action.timestamp };
      }
      current.actions.push(action);
    }
  }
  if (current) turns.push(current);
  return turns;
}

// --- Stats ---
function computeStats(actions: Action[] | undefined) {
  if (!actions || actions.length === 0) return null;
  let turns = 0, filesRead = 0, searches = 0, screenshots = 0, browserActions = 0;
  for (const a of actions) {
    if (a.type === "reasoning") turns++;
    if (a.type === "tool_call") {
      const p = a.payload as Record<string, unknown>;
      const tool = p?.tool as string;
      if (tool === "read_file") filesRead++;
      if (tool === "search_code") searches++;
      if (tool === "screenshot") screenshots++;
      if (["navigate", "click", "fill_field", "get_page_content"].includes(tool)) browserActions++;
    }
  }
  const first = actions[0].timestamp;
  const last = actions[actions.length - 1].timestamp;
  const sec = Math.round((last - first) / 1000);
  const duration = sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return { turns, filesRead, searches, screenshots, browserActions, duration };
}

// --- Action rendering (read-only — no human input) ---
function SharedActionItem({ action }: { action: Action }) {
  const [expanded, setExpanded] = useState(false);
  const payload = action.payload;
  const isObject = typeof payload === "object" && payload !== null;

  const time = new Date(action.timestamp).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });

  const ts = (opacity: string = "/40") => (
    <span className={`text-xs text-muted-foreground${opacity} shrink-0 w-16 text-right tabular-nums`}>
      {time}
    </span>
  );

  if (action.type === "observation") {
    return (
      <div className="flex items-center gap-3 py-1">
        <span className="w-3 shrink-0" />
        <span className="text-xs text-muted-foreground/60 flex-1 min-w-0 truncate italic">
          {typeof payload === "string" ? payload : JSON.stringify(payload)}
        </span>
        {ts("/20")}
      </div>
    );
  }

  if (action.type === "tool_call") {
    const tool = isObject ? (payload as Record<string, unknown>).tool : null;
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const input = isObject ? (payload as Record<string, unknown>).input : null;

    return (
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CollapsibleTrigger asChild>
          <button className="w-full flex items-center gap-3 py-0.5 text-left hover:bg-accent/30 transition-colors duration-100 group">
            <span className="w-3 shrink-0 text-xs text-muted-foreground/30 text-center group-hover:text-muted-foreground/60">
              {expanded ? "\u2212" : "+"}
            </span>
            <span className="text-xs text-rem/70 border border-rem/20 px-1.5 py-0.5 shrink-0">
              {String(tool || "tool")}
            </span>
            <span className="text-xs text-muted-foreground/70 flex-1 min-w-0 truncate">
              {summary ? String(summary) : ""}
            </span>
            {ts("/30")}
          </button>
        </CollapsibleTrigger>
        {!!input && (
          <CollapsibleContent>
            <pre className="ml-8 mr-2 mb-1 text-xs text-muted-foreground/50 overflow-x-auto max-h-40 whitespace-pre-wrap">
              {JSON.stringify(input, null, 2)}
            </pre>
          </CollapsibleContent>
        )}
      </Collapsible>
    );
  }

  if (action.type === "tool_result") {
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const content = isObject ? (payload as Record<string, unknown>).content : null;
    const storageId = isObject ? (payload as Record<string, unknown>).storageId as string | undefined : undefined;

    if (storageId) {
      return (
        <div>
          <div className="flex items-center gap-3 py-0.5">
            <span className="w-3 shrink-0" />
            <span className="text-xs text-muted-foreground/50 flex-1 min-w-0 truncate">
              {summary ? String(summary) : "screenshot captured"}
            </span>
            {ts("/30")}
          </div>
          <ScreenshotImage storageId={storageId} />
        </div>
      );
    }

    if (content) {
      return (
        <Collapsible open={expanded} onOpenChange={setExpanded}>
          <CollapsibleTrigger asChild>
            <button className="w-full flex items-center gap-3 py-0.5 text-left hover:bg-accent/30 transition-colors duration-100 group">
              <span className="w-3 shrink-0 text-xs text-muted-foreground/30 text-center group-hover:text-muted-foreground/60">
                {expanded ? "\u2212" : "+"}
              </span>
              <span className="text-xs text-muted-foreground/50 flex-1 min-w-0 truncate">
                {summary ? String(summary) : "result"}
              </span>
              {ts("/30")}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="ml-8 mr-2 mb-1 text-xs text-muted-foreground/40 overflow-x-auto max-h-60 whitespace-pre-wrap">
              {String(content).slice(0, 5000)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      );
    }

    return (
      <div className="flex items-center gap-3 py-0.5">
        <span className="w-3 shrink-0" />
        <span className="text-xs text-muted-foreground/50 flex-1 min-w-0 truncate">
          {summary ? String(summary) : "result"}
        </span>
        {ts("/30")}
      </div>
    );
  }

  // Human input request — read-only in shared view
  if (action.type === "human_input_request") {
    const question = isObject ? (payload as Record<string, unknown>).question as string : String(payload);
    return (
      <div className="ml-5 mr-2 my-2 border border-rem/30 bg-rem/5 p-4">
        <span className="text-xs text-rem/70 tracking-wider font-medium">OPERATOR INPUT REQUESTED</span>
        <p className="text-sm text-foreground mt-2">{question}</p>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 py-1">
      <span className="w-3 shrink-0" />
      <span className="text-xs text-foreground/60 flex-1 min-w-0 truncate">
        {typeof payload === "string" ? payload : JSON.stringify(payload)}
      </span>
      {ts()}
    </div>
  );
}

// --- Turn block ---
function SharedTurnBlock({ turn, isLatest, isRunning }: { turn: Turn; isLatest: boolean; isRunning: boolean }) {
  const time = new Date(turn.timestamp).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });

  return (
    <div className="animate-fade-slide-in">
      <div className="flex items-center gap-3 px-5 py-2.5">
        <span className="text-xs text-rem/40 tabular-nums tracking-wider">
          TURN {String(turn.index).padStart(2, "0")}
        </span>
        <span className="flex-1 border-t border-rem/10" />
        <span className="text-xs text-muted-foreground/40 tabular-nums">{time}</span>
      </div>

      {turn.reasoning && (
        <div className="mx-5 mb-3 border-l-2 border-l-rem/25 pl-4 py-2">
          <p className="text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap">
            {turn.reasoning}
            {isLatest && isRunning && (
              <span className="ml-1"><BlinkingCursor /></span>
            )}
          </p>
        </div>
      )}

      <div className="px-5 space-y-0.5 mb-2">
        {turn.actions.map((action) => (
          <SharedActionItem key={action._id} action={action} />
        ))}
      </div>
    </div>
  );
}

// --- Severity bar ---
function SeverityBar({ findings }: { findings: Array<{ severity: string }> }) {
  if (findings.length === 0) return null;
  const counts: Record<string, number> = {};
  for (const f of findings) counts[f.severity] = (counts[f.severity] || 0) + 1;
  const order = ["critical", "high", "medium", "low", "info"];
  const colors: Record<string, string> = {
    critical: "bg-destructive", high: "bg-destructive/70",
    medium: "bg-rem/40", low: "bg-rem/20", info: "bg-border",
  };
  return (
    <div className="flex h-[3px] w-full overflow-hidden">
      {order.map((sev) => {
        const count = counts[sev] || 0;
        if (count === 0) return null;
        return <div key={sev} className={colors[sev]} style={{ width: `${(count / findings.length) * 100}%` }} />;
      })}
    </div>
  );
}

// --- Agent label map ---
const AGENT_LABELS: Record<string, string> = {
  opus: "Opus 4.6",
  glm: "GLM-4.6V",
  nemotron: "Nemotron",
};

// --- Main shared page ---
export default function SharedScanPage() {
  const { token } = useParams<{ token: string }>();

  const scan = useQuery(api.scans.getByShareToken, { token: token ?? "" });
  const scanId = scan?._id;
  const actions = useQuery(
    api.actions.listByScan,
    scanId ? { scanId } : "skip",
  );
  const report = useQuery(
    api.reports.getByScan,
    scanId ? { scanId } : "skip",
  );

  const isRunning = scan?.status === "running" || scan?.status === "queued";
  const turns = useMemo(() => groupIntoTurns(actions ?? []), [actions]);
  const stats = useMemo(() => computeStats(actions), [actions]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const scrollToBottom = () => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => { if (autoScroll) scrollToBottom(); });
    for (const child of el.children) observer.observe(child);
    return () => observer.disconnect();
  });

  useEffect(() => {
    if (autoScroll) scrollToBottom();
  }, [actions?.length]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 60);
  };

  // Not found
  if (scan === null) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-base font-semibold mb-2">Link expired or invalid</h1>
          <p className="text-sm text-muted-foreground mb-4">This shared trace is no longer available.</p>
          <Link href="/" className="text-xs text-rem hover:underline">go to re:zero</Link>
        </div>
      </div>
    );
  }

  // Loading
  if (scan === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <img src="/rem-running.gif" alt="Rem" className="w-16 h-16 mx-auto mb-3 object-contain" />
          <p className="text-sm text-muted-foreground">Loading shared trace...</p>
        </div>
      </div>
    );
  }

  const hasReport = !!report;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="border-b border-border px-8 h-11 flex items-center justify-between shrink-0 mt-[2px]">
        <div className="flex items-center gap-8 text-sm">
          <Link href="/" className="tracking-tight hover:opacity-70 transition-opacity duration-150">
            <span className="font-semibold">re</span>
            <span className="text-destructive font-semibold">:</span>
            <span className="font-semibold">zero</span>
          </Link>
        </div>
        <span className="text-xs text-muted-foreground/50">shared trace</span>
      </header>

      {/* Scan info bar */}
      <div className="flex items-center gap-5 px-8 py-3 border-b border-border shrink-0">
        <span className="text-sm font-semibold">
          Rem ({AGENT_LABELS[scan.agent] || scan.agent})
        </span>
        <span className="text-xs flex items-center gap-2">
          {isRunning && <span className="inline-block w-1.5 h-1.5 bg-rem animate-pulse" />}
          <span className={isRunning ? "text-rem" : "text-muted-foreground"}>
            {scan.status}
          </span>
        </span>
        <div className="flex items-baseline gap-4 text-xs text-muted-foreground tabular-nums ml-auto">
          {stats && (
            <>
              <span>{stats.turns} turns</span>
              {stats.filesRead > 0 && <span>{stats.filesRead} files</span>}
              {stats.searches > 0 && <span>{stats.searches} searches</span>}
              {stats.browserActions > 0 && <span>{stats.browserActions} actions</span>}
              {stats.screenshots > 0 && <span>{stats.screenshots} screenshots</span>}
              <span>{stats.duration}</span>
            </>
          )}
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">
          {new Date(scan.startedAt).toLocaleString()}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {hasReport ? (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize={42} minSize={20}>
              {/* Trace */}
              <div className="h-full flex flex-col">
                <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
                  <div className="py-4">
                    {turns.map((turn, i) => (
                      <SharedTurnBlock
                        key={turn.index}
                        turn={turn}
                        isLatest={i === turns.length - 1}
                        isRunning={isRunning}
                      />
                    ))}
                    {isRunning && turns.length === 0 && (
                      <div className="px-5 py-8 text-center">
                        <RemSpinner />
                        <p className="text-xs text-muted-foreground mt-2">Rem is investigating...</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel defaultSize={58} minSize={25}>
              {/* Report */}
              <div className="h-full flex flex-col">
                <div className="px-6 py-4 border-b border-border shrink-0">
                  <div className="flex items-baseline gap-4 mb-1">
                    <h2 className="text-sm font-semibold">Report</h2>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {new Date(report.createdAt).toLocaleString()}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-3 text-xs text-muted-foreground tabular-nums mt-1">
                    <span>{report.findings.length} findings</span>
                    {(["critical", "high", "medium", "low", "info"] as const).map((sev) => {
                      const count = report.findings.filter((f) => f.severity === sev).length;
                      if (count === 0) return null;
                      return (
                        <span key={sev} className={sev === "critical" || sev === "high" ? "text-destructive" : ""}>
                          {count} {sev}
                        </span>
                      );
                    })}
                  </div>
                  <div className="mt-2">
                    <SeverityBar findings={report.findings} />
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto">
                  <div className="px-6 py-5">
                    {report.summary && (
                      <p className="text-sm text-muted-foreground leading-relaxed text-justify mb-6 pb-5 border-b border-border">
                        {report.summary}
                      </p>
                    )}
                    {report.findings.map((finding, i) => {
                      const sevBorder =
                        finding.severity === "critical" ? "border-l-destructive" :
                        finding.severity === "high" ? "border-l-destructive/60" :
                        finding.severity === "medium" ? "border-l-rem/50" :
                        finding.severity === "low" ? "border-l-rem/25" :
                        "border-l-border";
                      return (
                        <div
                          key={i}
                          className={`py-5 px-5 mb-3 border border-border border-l-[3px] ${sevBorder} bg-card/30`}
                        >
                          <div className="flex items-baseline gap-3 mb-2">
                            {finding.id && (
                              <span className="text-xs text-muted-foreground/50 tabular-nums tracking-wider">
                                {finding.id}
                              </span>
                            )}
                            <span className={`text-xs font-medium ${
                              finding.severity === "critical" || finding.severity === "high"
                                ? "text-destructive" : "text-muted-foreground"
                            }`}>
                              {finding.severity}
                            </span>
                            {finding.location && (
                              <>
                                <span className="text-xs text-muted-foreground/30">&middot;</span>
                                <span className="text-xs text-muted-foreground">{finding.location}</span>
                              </>
                            )}
                          </div>
                          <div className="text-sm font-medium mb-2">{finding.title}</div>
                          <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                            {finding.description}
                          </p>
                          {finding.codeSnippet && (
                            <pre className="mt-3 text-xs bg-muted/40 border border-border p-3 overflow-x-auto whitespace-pre-wrap">
                              {finding.codeSnippet}
                            </pre>
                          )}
                          {finding.recommendation && (
                            <div className="mt-3 bg-rem/5 border border-rem/15 px-4 py-3">
                              <span className="text-xs text-rem/50 font-medium tracking-wider block mb-1.5">REMEDIATION</span>
                              <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                                {finding.recommendation}
                              </p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          /* Trace only (no report yet) */
          <div className="h-full flex flex-col">
            <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
              <div className="py-4">
                {turns.map((turn, i) => (
                  <SharedTurnBlock
                    key={turn.index}
                    turn={turn}
                    isLatest={i === turns.length - 1}
                    isRunning={isRunning}
                  />
                ))}
                {isRunning && turns.length === 0 && (
                  <div className="px-5 py-8 text-center">
                    <RemSpinner />
                    <p className="text-xs text-muted-foreground mt-2">Rem is investigating...</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
