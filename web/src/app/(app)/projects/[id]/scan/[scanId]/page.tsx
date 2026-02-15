"use client";

import { useParams } from "next/navigation";
import { useQuery, useMutation } from "convex/react";
import { api } from "../../../../../../../convex/_generated/api";
import { Id } from "../../../../../../../convex/_generated/dataModel";
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
import { useMinLoading } from "@/hooks/use-min-loading";

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

// --- Terminal spinner for active state ---
const SPINNER_FRAMES = ["|", "/", "—", "\\"];

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

// --- Blinking cursor ---
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

// --- JSON display ---
function JsonBlock({ data }: { data: unknown }) {
  if (data === null || data === undefined) return null;
  const formatted = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="text-xs bg-muted/60 border border-rem/15 px-3 py-2 whitespace-pre-wrap overflow-x-auto text-foreground/60 leading-relaxed">
      {formatted}
    </pre>
  );
}

// --- Group flat actions into turns ---
function groupIntoTurns(actions: Action[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  for (const action of actions) {
    if (action.type === "reasoning") {
      // Start a new turn
      if (current) turns.push(current);
      current = {
        index: turns.length + 1,
        reasoning: typeof action.payload === "string" ? action.payload : JSON.stringify(action.payload),
        actions: [],
        timestamp: action.timestamp,
      };
    } else if (current) {
      current.actions.push(action);
    } else {
      // Actions before first reasoning — create an implicit turn 0
      if (!current) {
        current = {
          index: 1,
          reasoning: "",
          actions: [],
          timestamp: action.timestamp,
        };
      }
      current.actions.push(action);
    }
  }
  if (current) turns.push(current);

  return turns;
}

// --- Compute stats from actions ---
function computeStats(actions: Action[] | undefined) {
  if (!actions || actions.length === 0) return null;

  let filesRead = 0;
  let searches = 0;
  let turns = 0;
  let screenshots = 0;
  let browserActions = 0;

  for (const a of actions) {
    if (a.type === "reasoning") turns++;
    if (a.type === "tool_call") {
      const payload = a.payload as Record<string, unknown>;
      if (payload?.tool === "read_file") filesRead++;
      if (payload?.tool === "search_code") searches++;
      if (payload?.tool === "screenshot") screenshots++;
      if (payload?.tool === "navigate" || payload?.tool === "act" || payload?.tool === "observe" || payload?.tool === "extract" || payload?.tool === "execute_js") browserActions++;
    }
  }

  const first = actions[0].timestamp;
  const last = actions[actions.length - 1].timestamp;
  const durationMs = last - first;
  const durationStr = durationMs < 60000
    ? `${Math.round(durationMs / 1000)}s`
    : `${Math.floor(durationMs / 60000)}m ${Math.round((durationMs % 60000) / 1000)}s`;

  return { filesRead, searches, turns, screenshots, browserActions, duration: durationStr };
}

// --- Severity bar: proportional colored segments ---
function SeverityBar({ findings }: { findings: Array<{ severity: string }> }) {
  if (findings.length === 0) return null;

  const counts: Record<string, number> = {};
  for (const f of findings) {
    counts[f.severity] = (counts[f.severity] || 0) + 1;
  }

  const order = ["critical", "high", "medium", "low", "info"];
  const colors: Record<string, string> = {
    critical: "bg-destructive",
    high: "bg-destructive/70",
    medium: "bg-rem/40",
    low: "bg-rem/20",
    info: "bg-border",
  };

  return (
    <div className="flex h-[3px] w-full overflow-hidden">
      {order.map((sev) => {
        const count = counts[sev] || 0;
        if (count === 0) return null;
        const pct = (count / findings.length) * 100;
        return (
          <div
            key={sev}
            className={colors[sev]}
            style={{ width: `${pct}%` }}
          />
        );
      })}
    </div>
  );
}

// --- Human prompt input (ask_human tool) ---
function HumanPromptInput({ promptId, question }: { promptId: string; question: string }) {
  const respond = useMutation(api.prompts.respond);
  const prompt = useQuery(api.prompts.get, { promptId: promptId as Id<"prompts"> });
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isAnswered = prompt?.status === "answered";

  const handleSubmit = async () => {
    if (!value.trim() || submitting) return;
    setSubmitting(true);
    await respond({ promptId: promptId as Id<"prompts">, response: value.trim() });
    setSubmitting(false);
  };

  return (
    <div className="ml-5 mr-2 my-2 border border-rem/30 bg-rem/5 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-rem/70 tracking-wider font-medium">REM NEEDS YOUR INPUT</span>
        {!isAnswered && <RemSpinner />}
      </div>
      <p className="text-sm text-foreground mb-3">{question}</p>
      {isAnswered ? (
        <div className="text-sm text-muted-foreground border-l-2 border-l-rem/30 pl-3">
          {prompt.response}
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
            placeholder="Type your response..."
            autoFocus
            className="flex-1 text-sm bg-transparent border border-border px-3 py-2 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
          />
          <button
            onClick={handleSubmit}
            disabled={!value.trim() || submitting}
            className="text-sm border border-rem/30 text-rem/70 px-4 py-2 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100 disabled:opacity-30 active:translate-y-px"
          >
            {submitting ? "sending..." : "send"}
          </button>
        </div>
      )}
    </div>
  );
}

// --- Action rendering within a turn ---
function TurnActionItem({ action }: { action: Action }) {
  const [expanded, setExpanded] = useState(false);
  const payload = action.payload;
  const isObject = typeof payload === "object" && payload !== null;

  const time = new Date(action.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  // Shared timestamp element — fixed-width column so all rows align
  const ts = (opacity: string = "/40") => (
    <span className={`text-xs text-muted-foreground${opacity} shrink-0 w-16 text-right tabular-nums`}>
      {time}
    </span>
  );

  // Observation: system messages
  if (action.type === "observation") {
    return (
      <div className="flex items-center gap-3 py-1">
        <span className="w-3 shrink-0" />
        <span className="text-xs text-muted-foreground/70 flex-1 min-w-0 truncate">
          {typeof payload === "string" ? payload : JSON.stringify(payload)}
        </span>
        {ts()}
      </div>
    );
  }

  // Tool call: expandable
  if (action.type === "tool_call") {
    const tool = isObject ? String((payload as Record<string, unknown>).tool) : "?";
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const input = isObject ? (payload as Record<string, unknown>).input : null;

    return (
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CollapsibleTrigger asChild>
          <button className="w-full text-left flex items-center gap-3 py-1 hover:bg-rem/5 transition-colors duration-100 cursor-pointer">
            <span className="text-xs text-muted-foreground/50 shrink-0 w-3 tabular-nums">
              {expanded ? "\u2212" : "+"}
            </span>
            <span className="text-xs text-rem/70 border border-rem/20 px-1.5 py-px shrink-0">
              {tool}
            </span>
            <span className="text-sm text-foreground/70 truncate flex-1 min-w-0">
              {summary ? String(summary) : ""}
            </span>
            {ts()}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="ml-8 mr-2 mb-2 mt-1">
            {input != null && <JsonBlock data={input} />}
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  }

  // Tool result: expandable if it has content, screenshot if storageId, otherwise compact inline
  if (action.type === "tool_result") {
    const summary = isObject ? (payload as Record<string, unknown>).summary : null;
    const content = isObject ? (payload as Record<string, unknown>).content : null;
    const storageId = isObject ? (payload as Record<string, unknown>).storageId as string | undefined : undefined;

    // Screenshot result
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
            <button className="w-full text-left flex items-center gap-3 py-0.5 hover:bg-rem/5 transition-colors duration-100 cursor-pointer">
              <span className="text-xs text-muted-foreground/50 shrink-0 w-3 tabular-nums">
                {expanded ? "\u2212" : "+"}
              </span>
              <span className="text-xs text-muted-foreground/50 flex-1 min-w-0 truncate">
                {summary ? String(summary) : "result"}
              </span>
              {ts("/30")}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="ml-8 mr-2 mb-2 mt-1">
              <pre className="text-xs bg-muted/60 border border-border px-3 py-2 whitespace-pre-wrap overflow-x-auto max-h-80 overflow-y-auto text-foreground/60 leading-relaxed">
                {String(content)}
              </pre>
            </div>
          </CollapsibleContent>
        </Collapsible>
      );
    }

    return (
      <div className="flex items-center gap-3 py-0.5">
        <span className="w-3 shrink-0" />
        <span className="text-xs text-muted-foreground/50 flex-1 min-w-0 truncate">
          {summary
            ? String(summary)
            : typeof payload === "string"
              ? payload
              : JSON.stringify(payload)}
        </span>
        {ts("/30")}
      </div>
    );
  }

  // Human input request
  if (action.type === "human_input_request") {
    const promptId = isObject ? (payload as Record<string, unknown>).promptId as string : null;
    const question = isObject ? (payload as Record<string, unknown>).question as string : String(payload);

    if (promptId) {
      return <HumanPromptInput promptId={promptId} question={question} />;
    }
  }

  // Fallback
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
function TurnBlock({ turn, isLatest, isRunning }: { turn: Turn; isLatest: boolean; isRunning: boolean }) {
  const time = new Date(turn.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  return (
    <div className="animate-fade-slide-in">
      {/* Turn header */}
      <div className="flex items-center gap-3 px-5 py-2.5">
        <span className="text-xs text-rem/40 tabular-nums tracking-wider">
          TURN {String(turn.index).padStart(2, "0")}
        </span>
        <span className="flex-1 border-t border-rem/10" />
        <span className="text-xs text-muted-foreground/40 tabular-nums">{time}</span>
      </div>

      {/* Reasoning */}
      {turn.reasoning && (
        <div className="px-5 py-2">
          <div className="border-l-2 border-rem/25 pl-4">
            <p className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
              {turn.reasoning}
            </p>
            {isLatest && isRunning && (
              <span className="inline-block mt-1">
                <BlinkingCursor />
              </span>
            )}
          </div>
        </div>
      )}

      {/* Actions within this turn */}
      {turn.actions.length > 0 && (
        <div className="px-5 py-1 space-y-0">
          {turn.actions.map((action) => (
            <TurnActionItem key={action._id} action={action} />
          ))}
        </div>
      )}
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
      id?: string;
      title: string;
      severity: string;
      description: string;
      location?: string;
      recommendation?: string;
      codeSnippet?: string;
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
      {/* Header */}
      <div className="px-6 py-4 border-b border-border shrink-0">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-base font-semibold">Report</h2>
          <div className="flex items-baseline gap-4 text-xs text-muted-foreground">
            <span>{report.findings.length} findings</span>
            {(["critical", "high", "medium", "low", "info"] as const).map((sev) => {
              const count = severityCounts[sev] || 0;
              if (count === 0) return null;
              return (
                <span
                  key={sev}
                  className={
                    sev === "critical" || sev === "high"
                      ? "text-destructive"
                      : ""
                  }
                >
                  {count} {sev}
                </span>
              );
            })}
          </div>
        </div>
        <SeverityBar findings={report.findings} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-5">
          {report.summary && (
            <p className="text-sm text-muted-foreground leading-relaxed text-justify mb-6 pb-6 border-b border-border">
              {report.summary}
            </p>
          )}

          {report.findings.map((finding, i) => (
            <div
              key={i}
              className="py-5 border-b border-border last:border-b-0 animate-fade-slide-in"
              style={{ animationDelay: `${i * 50}ms` }}
            >
              {/* ID + Severity */}
              <div className="flex items-baseline gap-3 mb-2">
                {finding.id && (
                  <span className="text-xs text-muted-foreground/50 tabular-nums tracking-wider">
                    {finding.id}
                  </span>
                )}
                <span
                  className={`text-xs font-medium ${
                    finding.severity === "critical" || finding.severity === "high"
                      ? "text-destructive"
                      : "text-muted-foreground"
                  }`}
                >
                  {finding.severity}
                </span>
                {finding.location && !finding.codeSnippet && (
                  <>
                    <span className="text-xs text-muted-foreground/30">&middot;</span>
                    <span className="text-xs text-muted-foreground">
                      {finding.location}
                    </span>
                  </>
                )}
              </div>

              {/* Title */}
              <div className="text-sm font-medium mb-2">{finding.title}</div>

              {/* Description */}
              <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                {finding.description}
              </p>

              {/* Code snippet with file header + line numbers */}
              {finding.codeSnippet && (() => {
                const locMatch = finding.location?.match(/^(.+?):(\d+)(?:-(\d+))?/);
                const file = locMatch?.[1];
                const startLine = locMatch ? parseInt(locMatch[2]) : 1;
                const lines = finding.codeSnippet.split("\n");
                if (lines[lines.length - 1] === "") lines.pop();
                const gutterWidth = String(startLine + lines.length - 1).length;

                return (
                  <div className="mt-3 border border-border overflow-hidden">
                    {file && (
                      <div className="px-3 py-1.5 bg-muted/80 border-b border-border flex items-baseline gap-3">
                        <span className="text-xs text-muted-foreground font-mono">{file}</span>
                        <span className="text-xs text-muted-foreground/40 font-mono tabular-nums">
                          L{locMatch![2]}{locMatch![3] ? `–${locMatch![3]}` : ""}
                        </span>
                      </div>
                    )}
                    <div className="bg-muted/40 overflow-x-auto">
                      <table className="w-full text-xs leading-relaxed font-mono border-collapse">
                        <tbody>
                          {lines.map((line, j) => (
                            <tr key={j} className="hover:bg-muted/60">
                              <td className="text-muted-foreground/30 text-right pr-3 pl-3 py-0 select-none whitespace-nowrap tabular-nums border-r border-border/50" style={{ width: `${gutterWidth + 2}ch` }}>
                                {startLine + j}
                              </td>
                              <td className="text-foreground/70 pl-3 pr-4 py-0 whitespace-pre">
                                {line}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })()}

              {/* Recommendation */}
              {finding.recommendation && (
                <div className="mt-3 bg-rem/5 border border-rem/15 px-4 py-3">
                  <span className="text-xs text-rem/50 font-medium tracking-wider block mb-1.5">REMEDIATION</span>
                  <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                    {finding.recommendation}
                  </p>
                </div>
              )}
            </div>
          ))}
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
  actions: Action[] | undefined;
  isRunning: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [scrollProgress, setScrollProgress] = useState(0);

  const turns = useMemo(() => groupIntoTurns(actions ?? []), [actions]);
  const stats = useMemo(() => computeStats(actions), [actions]);

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  };

  // Auto-scroll on any content size change (new actions, image loads, expands)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (autoScroll) scrollToBottom();
    });
    // Observe the scrollable content, not the container itself
    for (const child of el.children) observer.observe(child);
    return () => observer.disconnect();
  });

  // Also scroll when new actions arrive
  useEffect(() => {
    if (autoScroll) scrollToBottom();
  }, [actions?.length]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 60;
    setAutoScroll(isAtBottom);
    setShowScrollButton(!isAtBottom);
    setScrollProgress(scrollHeight > clientHeight ? scrollTop / (scrollHeight - clientHeight) : 0);
  };

  return (
    <div className="h-full flex flex-col relative">
      {/* Header + stats */}
      <div className="px-6 py-4 border-b border-border shrink-0">
        <div className="flex items-baseline justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold">Trace</h2>
            {isRunning && <RemSpinner />}
          </div>
          <div className="flex items-baseline gap-4 text-xs text-muted-foreground tabular-nums">
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
            {!stats && <span>0 actions</span>}
          </div>
        </div>
        {/* Scroll progress bar */}
        <div className="h-px bg-border mt-3 -mb-px relative">
          <div
            className="absolute top-0 left-0 h-px bg-rem/60 transition-[width] duration-100"
            style={{ width: `${scrollProgress * 100}%` }}
          />
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        <div className="py-2">
          {(!actions || actions.length === 0) && (
            <div className="flex items-center justify-center py-20">
              <div className="text-center">
                {isRunning ? (
                  <>
                    <img src="/rem-running.gif" alt="Rem" className="w-20 h-20 mx-auto mb-3 object-contain" />
                    <p className="text-sm text-rem">Rem is suiting up...</p>
                    <p className="text-xs text-muted-foreground mt-1">spinning up sandbox environment</p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Waiting for Rem...</p>
                )}
              </div>
            </div>
          )}

          {turns.map((turn, i) => (
            <TurnBlock
              key={turn.index}
              turn={turn}
              isLatest={i === turns.length - 1}
              isRunning={isRunning}
            />
          ))}

          {isRunning && actions && actions.length > 0 && (
            <div className="flex items-center gap-3 px-5 py-4 text-sm text-rem/80">
              <img src="/rem-running.gif" alt="Rem" className="w-6 h-6 object-contain" />
              <RemSpinner />
              Rem is investigating...
            </div>
          )}
        </div>
      </div>

      {showScrollButton && (
        <button
          className="absolute bottom-4 right-4 text-xs border border-border bg-background px-2.5 py-1.5 text-muted-foreground hover:text-rem hover:border-rem/40 transition-colors duration-100"
          onClick={() => {
            setAutoScroll(true);
            scrollToBottom();
          }}
        >
          scroll to bottom
        </button>
      )}
    </div>
  );
}

// --- Agent label map ---
const AGENT_LABELS: Record<string, string> = {
  opus: "Opus 4.6",
  glm47v: "GLM-4.7V",
  nemotron: "Nemotron",
};

// --- Main page ---
export default function ScanPage() {
  const { id, scanId } = useParams<{ id: string; scanId: string }>();
  const projectId = id as Id<"projects">;
  const project = useQuery(api.projects.get, { projectId });
  const scan = useQuery(api.scans.get, {
    scanId: scanId as Id<"scans">,
  });
  const actions = useQuery(api.actions.listByScan, {
    scanId: scanId as Id<"scans">,
  });
  const report = useQuery(api.reports.getByScan, {
    scanId: scanId as Id<"scans">,
  });

  const generateShareToken = useMutation(api.scans.generateShareToken);
  const revokeShareToken = useMutation(api.scans.revokeShareToken);

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  const handleShare = async () => {
    setSharing(true);
    const token = await generateShareToken({ scanId: scanId as Id<"scans"> });
    const url = `${window.location.origin}/share/${token}`;
    setShareUrl(url);
    await navigator.clipboard.writeText(url);
    setSharing(false);
  };

  const handleRevokeShare = async () => {
    await revokeShareToken({ scanId: scanId as Id<"scans"> });
    setShareUrl(null);
  };

  const minTime = useMinLoading();

  // Toggle body.scanning class for brand line pulse
  const isRunning = scan?.status === "running" || scan?.status === "queued";
  useEffect(() => {
    if (isRunning) {
      document.body.classList.add("scanning");
    } else {
      document.body.classList.remove("scanning");
    }
    return () => document.body.classList.remove("scanning");
  }, [isRunning]);

  if (!scan || !minTime) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <div className="text-center">
          <img src="/rem-running.gif" alt="Rem" className="w-16 h-16 mx-auto mb-3 object-contain" />
          <p className="text-sm text-muted-foreground">Rem is on her way...</p>
        </div>
      </div>
    );
  }

  const hasReport = !!report;

  return (
    <div className="flex flex-col h-[calc(100vh-3.25rem)]">
      {/* Scan header with breadcrumbs */}
      <div className="flex items-center gap-5 px-8 py-3 border-b border-border shrink-0">
        <div className="flex items-baseline gap-2">
          <Link href="/dashboard" className="text-sm text-muted-foreground hover:text-rem transition-colors duration-150">
            projects
          </Link>
          <span className="text-xs text-muted-foreground/30">/</span>
          <Link href={`/projects/${projectId}`} className="text-sm text-muted-foreground hover:text-rem transition-colors duration-150">
            {project?.name ?? "..."}
          </Link>
          <span className="text-xs text-muted-foreground/30">/</span>
          <span className="text-sm font-semibold">
            Rem ({AGENT_LABELS[scan.agent] || scan.agent})
          </span>
        </div>
        <span className="text-xs flex items-center gap-2">
          {isRunning && (
            <span className="inline-block w-1.5 h-1.5 bg-rem animate-pulse" />
          )}
          <span className={isRunning ? "text-rem" : "text-muted-foreground"}>
            {scan.status}
          </span>
        </span>
        <div className="flex items-center gap-3 ml-auto">
          {shareUrl ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-rem/60">link copied</span>
              <button
                onClick={handleRevokeShare}
                className="text-xs border border-destructive/30 text-destructive/60 px-2 py-1 hover:bg-destructive/10 hover:border-destructive hover:text-destructive transition-all duration-100"
              >
                revoke
              </button>
            </div>
          ) : scan.shareToken ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  const url = `${window.location.origin}/share/${scan.shareToken}`;
                  navigator.clipboard.writeText(url);
                  setShareUrl(url);
                }}
                className="text-xs border border-rem/30 text-rem/60 px-2 py-1 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100"
              >
                copy link
              </button>
              <button
                onClick={handleRevokeShare}
                className="text-xs border border-destructive/30 text-destructive/60 px-2 py-1 hover:bg-destructive/10 hover:border-destructive hover:text-destructive transition-all duration-100"
              >
                revoke
              </button>
            </div>
          ) : (
            <button
              onClick={handleShare}
              disabled={sharing}
              className="text-xs border border-border text-muted-foreground/60 px-2 py-1 hover:bg-rem/10 hover:border-rem/40 hover:text-rem transition-all duration-100 disabled:opacity-30"
            >
              {sharing ? "sharing..." : "share"}
            </button>
          )}
          <span className="text-xs text-muted-foreground tabular-nums">
            {new Date(scan.startedAt).toLocaleString()}
          </span>
        </div>
      </div>

      {/* Content — full viewport width */}
      <div className="flex-1 min-h-0">
        {hasReport ? (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel defaultSize={42} minSize={20}>
              <TracePanel actions={actions} isRunning={isRunning} />
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel defaultSize={58} minSize={25}>
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
