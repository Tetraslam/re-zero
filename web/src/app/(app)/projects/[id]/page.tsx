"use client";

import { useParams } from "next/navigation";
import { useQuery, useMutation } from "convex/react";
import { api } from "../../../../../convex/_generated/api";
import { Id } from "../../../../../convex/_generated/dataModel";
import Link from "next/link";
import { useMemo, useState, useEffect, useRef } from "react";
import { useMinLoading } from "@/hooks/use-min-loading";
import { useApiKey } from "@/hooks/use-api-key";
import { useCustomer } from "autumn-js/react";
import { useCurrentUser } from "@/hooks/use-current-user";
import { TIER_CONFIG, DEFAULT_TIER, getScanLabel, getScanShort, type Tier } from "@/lib/scan-tiers";

function SeverityBar({ findings }: { findings: Array<{ severity: string }> }) {
  if (findings.length === 0) return null;
  const counts: Record<string, number> = {};
  for (const f of findings) counts[f.severity] = (counts[f.severity] || 0) + 1;
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
        return <div key={sev} className={colors[sev]} style={{ width: `${(count / findings.length) * 100}%` }} />;
      })}
    </div>
  );
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id as Id<"projects">;

  const project = useQuery(api.projects.get, { projectId });
  const scans = useQuery(api.scans.listByProject, { projectId });
  const reports = useQuery(api.reports.listByProject, { projectId });
  const createScan = useMutation(api.scans.create);
  const updateTargetConfig = useMutation(api.projects.updateTargetConfig);
  const apiKey = useApiKey();

  const { customer } = useCustomer();
  const { user: currentUser } = useCurrentUser();
  const [starting, setStarting] = useState(false);
  const [tierInitialized, setTierInitialized] = useState(false);
  const [selectedTier, setSelectedTier] = useState<Tier>(DEFAULT_TIER);
  const [selectedModel, setSelectedModel] = useState<string>(TIER_CONFIG[DEFAULT_TIER].defaultModel);
  const [showDeploy, setShowDeploy] = useState(false);
  const deployRef = useRef<HTMLDivElement>(null);
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);

  // Prepaid scan balance from Autumn
  const maidBalance = (customer?.features as any)?.standard_scan?.balance ?? 0;

  // Initialize tier from user preference (once)
  useEffect(() => {
    if (!tierInitialized && currentUser?.defaultTier) {
      const t = currentUser.defaultTier as Tier;
      setSelectedTier(t);
      setSelectedModel(TIER_CONFIG[t].defaultModel);
      setTierInitialized(true);
    } else if (!tierInitialized && currentUser) {
      setTierInitialized(true);
    }
  }, [currentUser, tierInitialized]);

  // Close deploy dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (deployRef.current && !deployRef.current.contains(e.target as Node)) {
        setShowDeploy(false);
      }
    }
    if (showDeploy) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showDeploy]);
  const [showCreds, setShowCreds] = useState(false);
  const [credUsername, setCredUsername] = useState("");
  const [credPassword, setCredPassword] = useState("");
  const [credContext, setCredContext] = useState("");
  const [savingCreds, setSavingCreds] = useState(false);
  const minTime = useMinLoading();

  // Sync local cred state when project loads
  useEffect(() => {
    if (project?.targetType === "web") {
      if (project.targetConfig?.testAccount) {
        setCredUsername(project.targetConfig.testAccount.username || "");
        setCredPassword(project.targetConfig.testAccount.password || "");
      }
      setCredContext(project.targetConfig?.context || "");
    }
  }, [project?.targetConfig?.testAccount, project?.targetConfig?.context, project?.targetType]);

  const handleSaveCreds = async () => {
    if (!project) return;
    setSavingCreds(true);
    const newConfig = { ...project.targetConfig };
    if (credUsername.trim()) {
      newConfig.testAccount = { username: credUsername.trim(), password: credPassword };
    } else {
      delete newConfig.testAccount;
    }
    if (credContext.trim()) {
      newConfig.context = credContext.trim();
    } else {
      delete newConfig.context;
    }
    await updateTargetConfig({ projectId, targetConfig: newConfig });
    setSavingCreds(false);
    setShowCreds(false);
  };

  const handleRemoveCreds = async () => {
    if (!project) return;
    setSavingCreds(true);
    const newConfig = { ...project.targetConfig };
    delete newConfig.testAccount;
    delete newConfig.context;
    await updateTargetConfig({ projectId, targetConfig: newConfig });
    setCredUsername("");
    setCredPassword("");
    setCredContext("");
    setSavingCreds(false);
    setShowCreds(false);
  };

  const reportByScan = useMemo(() => {
    const map = new Map<string, NonNullable<typeof reports>[number]>();
    if (reports) {
      for (const r of reports) map.set(r.scanId, r);
    }
    return map;
  }, [reports]);

  // Auto-select the first scan with a report if nothing is selected
  const effectiveSelectedId = useMemo(() => {
    if (selectedScanId) return selectedScanId;
    if (scans && scans.length > 0) {
      // Prefer first scan that has a report
      const withReport = scans.find((s) => reportByScan.has(s._id));
      if (withReport) return withReport._id;
      // Otherwise first running scan
      const running = scans.find((s) => s.status === "running" || s.status === "queued");
      if (running) return running._id;
      return scans[0]._id;
    }
    return null;
  }, [selectedScanId, scans, reportByScan]);

  const handleStartScan = async () => {
    if (!project || !apiKey) return;
    setStarting(true);
    setShowDeploy(false);
    const tier = selectedTier;
    const model = selectedModel;
    const scanId = await createScan({ projectId, tier, model });
    try {
      await fetch(`${process.env.NEXT_PUBLIC_SERVER_URL}/scans/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({
          scan_id: scanId,
          project_id: projectId,
          target_type: project.targetType,
          target_config: project.targetConfig,
          tier,
          model,
        }),
      });
    } catch (err) {
      console.error("Failed to start scan:", err);
    }
    setStarting(false);
  };

  if (!project || !minTime) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <div className="text-center">
          <img src="/rem-running.gif" alt="Rem" className="w-16 h-16 mx-auto mb-3 object-contain" />
          <p className="text-sm text-muted-foreground">Loading project...</p>
        </div>
      </div>
    );
  }

  const hasScans = scans && scans.length > 0;
  const selectedScan = scans?.find((s) => s._id === effectiveSelectedId);
  const selectedReport = effectiveSelectedId ? reportByScan.get(effectiveSelectedId) : null;

  return (
    <div className="flex flex-col h-[calc(100vh-3.25rem)]">
      {/* Top bar: project info + deploy buttons */}
      <div className={`px-6 py-3 border-b border-border shrink-0 flex items-center justify-between gap-6 relative ${
        selectedTier === "oni" ? "border-b-rem/30" : ""
      }`}>
        {/* Oni ambient shimmer */}
        {selectedTier === "oni" && (
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            <div className="absolute inset-0 animate-oni-shimmer" />
          </div>
        )}
        <div className="flex items-baseline gap-2 min-w-0">
          <Link href="/dashboard" className="text-sm text-muted-foreground hover:text-rem transition-colors duration-150 shrink-0">
            projects
          </Link>
          <span className="text-xs text-muted-foreground/30 shrink-0">/</span>
          <h1 className="text-sm font-semibold shrink-0">{project.name}</h1>
          <span className="text-xs text-muted-foreground/30 shrink-0">&middot;</span>
          <span className="text-xs text-muted-foreground shrink-0">{project.targetType}</span>
          {project.targetType === "oss" && project.targetConfig?.repoUrl && (
            <a href={project.targetConfig.repoUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground hover:text-rem transition-colors duration-150 truncate">
              {project.targetConfig.repoUrl}
            </a>
          )}
          {project.targetType === "web" && project.targetConfig?.url && (
            <a href={project.targetConfig.url} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground hover:text-rem transition-colors duration-150 truncate">
              {project.targetConfig.url}
            </a>
          )}
          {project.targetType === "web" && (
            <>
              <span className="text-xs text-muted-foreground/30 shrink-0">&middot;</span>
              <button
                onClick={() => setShowCreds(!showCreds)}
                className={`text-xs transition-colors duration-150 shrink-0 ${
                  project.targetConfig?.testAccount || project.targetConfig?.context
                    ? "text-rem/70 hover:text-rem"
                    : "text-muted-foreground/50 hover:text-rem"
                }`}
              >
                {project.targetConfig?.testAccount || project.targetConfig?.context ? "config" : "+ config"}
              </button>
            </>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {maidBalance > 0 && (
            <span className="text-xs tabular-nums text-muted-foreground/40">
              {maidBalance} {maidBalance === 1 ? "scan" : "scans"} remaining
            </span>
          )}
          {/* Mode indicator */}
          <span className={`text-[10px] tracking-wider px-1.5 py-0.5 select-none transition-all duration-300 ${
            selectedTier === "oni"
              ? "bg-rem text-white animate-oni-badge"
              : "border border-rem/20 text-rem/50"
          }`}>
            {TIER_CONFIG[selectedTier].label.toUpperCase()}
          </span>
          <div className="relative" ref={deployRef}>
            <div className={`flex items-stretch transition-all duration-300 ${
              selectedTier === "oni" ? "animate-oni-glow" : ""
            }`}>
              <button
                onClick={handleStartScan}
                disabled={starting}
                className={`text-xs px-2.5 flex items-center transition-all duration-200 disabled:opacity-30 active:translate-y-px border-r-0 ${
                  selectedTier === "oni"
                    ? "border border-rem bg-rem text-white hover:bg-rem/90"
                    : "border border-rem/30 text-rem/70 hover:bg-rem/10 hover:border-rem hover:text-rem"
                }`}
                style={{ paddingTop: 6, paddingBottom: 6 }}
              >
                + Deploy Rem
              </button>
              <button
                onClick={() => setShowDeploy(!showDeploy)}
                className={`text-xs flex items-center justify-center transition-all duration-200 active:translate-y-px ${
                  selectedTier === "oni"
                    ? showDeploy
                      ? "border border-rem bg-white/20 text-white"
                      : "border border-rem bg-rem text-white hover:bg-rem/90"
                    : showDeploy
                      ? "border border-rem bg-rem/10 text-rem"
                      : "border border-rem/30 text-rem/70 hover:bg-rem/10 hover:border-rem hover:text-rem"
                }`}
                style={{ paddingTop: 6, paddingBottom: 6, paddingLeft: 6, paddingRight: 6 }}
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                  <path d={showDeploy ? "M2 6.5L5 3.5L8 6.5" : "M2 3.5L5 6.5L8 3.5"} />
                </svg>
              </button>
            </div>
            {/* Tier + model dropdown */}
            {showDeploy && (
              <div className="absolute right-0 top-full mt-1 border border-border bg-background z-50 min-w-[220px] shadow-sm">
                {(Object.keys(TIER_CONFIG) as Tier[]).map((t) => {
                  const isTierActive = selectedTier === t;
                  return (
                    <div key={t}>
                      <div className={`px-3 py-1.5 text-[10px] tracking-wider border-b transition-all duration-150 ${
                        isTierActive
                          ? t === "oni"
                            ? "text-white bg-rem border-rem/50 font-medium"
                            : "text-rem/70 bg-rem/5 border-border/50"
                          : "text-muted-foreground/50 border-border/50"
                      }`}>
                        {TIER_CONFIG[t].label.toUpperCase()}
                        <span className={`ml-2 ${isTierActive && t === "oni" ? "text-white/50" : "text-muted-foreground/30"}`}>
                          ${TIER_CONFIG[t].price}
                        </span>
                      </div>
                      {Object.entries(TIER_CONFIG[t].models).map(([key, m]) => {
                        const isSelected = selectedTier === t && selectedModel === key;
                        return (
                          <button
                            key={key}
                            onClick={() => {
                              setSelectedTier(t);
                              setSelectedModel(key);
                              setShowDeploy(false);
                            }}
                            className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-all duration-100 ${
                              isSelected
                                ? "text-rem bg-rem/8"
                                : "text-foreground/80 hover:bg-card/80 hover:text-foreground"
                            }`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              isSelected ? "bg-rem" : "bg-border"
                            }`} />
                            {(m as { label: string }).label}
                            {key === TIER_CONFIG[t].defaultModel && (
                              <span className="text-muted-foreground/30 ml-auto text-[10px]">default</span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Scan config panel */}
      {showCreds && project.targetType === "web" && (
        <div className="px-6 py-3 border-b border-border shrink-0 bg-card/30 space-y-3">
          <div className="flex items-center gap-3">
            <label className="text-xs text-muted-foreground shrink-0">test account</label>
            <input
              value={credUsername}
              onChange={(e) => setCredUsername(e.target.value)}
              placeholder="username or email"
              className="text-xs bg-transparent border border-border px-2.5 py-1.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150 w-48"
            />
            <input
              type="password"
              value={credPassword}
              onChange={(e) => setCredPassword(e.target.value)}
              placeholder="password"
              className="text-xs bg-transparent border border-border px-2.5 py-1.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150 w-48"
            />
          </div>
          <div className="flex items-start gap-3">
            <label className="text-xs text-muted-foreground shrink-0 pt-1.5">context</label>
            <textarea
              value={credContext}
              onChange={(e) => setCredContext(e.target.value)}
              placeholder={"Hidden routes, tech stack details, areas of concern, how to use the test account..."}
              rows={2}
              className="flex-1 text-xs bg-transparent border border-border px-2.5 py-1.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150 resize-y"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveCreds}
              disabled={savingCreds}
              className="text-xs border border-rem/30 text-rem/70 px-2.5 py-1.5 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100 disabled:opacity-30"
            >
              {savingCreds ? "saving..." : "save"}
            </button>
            {(project.targetConfig?.testAccount || project.targetConfig?.context) && (
              <button
                onClick={handleRemoveCreds}
                disabled={savingCreds}
                className="text-xs border border-destructive/30 text-destructive/70 px-2.5 py-1.5 hover:bg-destructive/10 hover:border-destructive hover:text-destructive transition-all duration-100 disabled:opacity-30"
              >
                clear all
              </button>
            )}
            <p className="text-xs text-muted-foreground/40 ml-auto">
              Context and credentials are injected into Rem&apos;s system prompt for each scan
            </p>
          </div>
        </div>
      )}

      {/* Main area: scan sidebar + report */}
      <div className="flex-1 flex min-h-0">
        {/* Scan sidebar */}
        <div className="w-80 shrink-0 border-r border-border flex flex-col">
          <div className="px-4 py-3 text-xs text-muted-foreground border-b border-border shrink-0">
            {scans?.length ?? 0} scans
          </div>
          <div className="flex-1 overflow-y-auto">
            {!hasScans && (
              <div className="px-4 py-8 text-center">
                <img src="/rem-running.gif" alt="Rem" className="w-10 h-10 mx-auto mb-2 object-contain opacity-50" />
                <p className="text-xs text-muted-foreground">No scans yet.</p>
              </div>
            )}

            {scans?.map((scan) => {
              const scanReport = reportByScan.get(scan._id);
              const isRunning = scan.status === "running" || scan.status === "queued";
              const isFailed = scan.status === "failed";
              const isSelected = effectiveSelectedId === scan._id;
              const findingCount = scanReport?.findings.length ?? 0;
              const critHigh = scanReport?.findings.filter(
                (f) => f.severity === "critical" || f.severity === "high"
              ).length ?? 0;

              return (
                <button
                  key={scan._id}
                  onClick={() => setSelectedScanId(scan._id)}
                  className={`w-full text-left px-4 py-3 border-b border-border transition-all duration-100 ${
                    isSelected
                      ? "bg-rem/8 border-l-2 border-l-rem"
                      : "border-l-2 border-l-transparent hover:bg-accent/40 hover:border-l-rem/50"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      {isRunning && (
                        <span className="inline-block w-1.5 h-1.5 bg-rem animate-pulse shrink-0" />
                      )}
                      <span className={`text-sm ${isSelected ? "text-rem" : "text-foreground"}`}>
                        {getScanShort(scan)}
                      </span>
                    </div>
                    {isFailed && (
                      <span className="text-xs text-destructive">failed</span>
                    )}
                  </div>
                  <div className="flex items-baseline gap-3 text-xs text-muted-foreground">
                    {isRunning && <span className="text-rem">running</span>}
                    {!isRunning && !isFailed && findingCount > 0 && (
                      <>
                        <span>{findingCount} findings</span>
                        {critHigh > 0 && (
                          <span className="text-destructive">{critHigh} crit/high</span>
                        )}
                      </>
                    )}
                    {!isRunning && !isFailed && findingCount === 0 && (
                      <span>no findings</span>
                    )}
                    <span className="ml-auto tabular-nums">
                      {new Date(scan.startedAt).toLocaleDateString()}
                    </span>
                  </div>
                  {scanReport && findingCount > 0 && (
                    <div className="mt-2">
                      <SeverityBar findings={scanReport.findings} />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Report detail panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* No scan selected / no scans exist */}
          {!selectedScan && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <img src="/rem-running.gif" alt="Rem" className="w-16 h-16 mx-auto mb-3 object-contain opacity-60" />
                <p className="text-sm text-foreground mb-1">Rem is waiting for orders.</p>
                <p className="text-xs text-muted-foreground">Deploy a scan to get started.</p>
              </div>
            </div>
          )}

          {/* Selected scan: running, no report yet */}
          {selectedScan && !selectedReport && (selectedScan.status === "running" || selectedScan.status === "queued") && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <img src="/rem-running.gif" alt="Rem" className="w-20 h-20 mx-auto mb-3 object-contain" />
                <p className={`text-sm mb-1 ${selectedScan.tier === "oni" ? "text-rem font-medium" : "text-rem"}`}>
                  {selectedScan.tier === "oni"
                    ? `Rem (${getScanShort(selectedScan)}) is tearing through the code...`
                    : `Rem (${getScanShort(selectedScan)}) is investigating...`
                  }
                </p>
                <Link
                  href={`/projects/${projectId}/scan/${selectedScan._id}`}
                  className="text-xs border border-rem/30 text-rem/70 px-2.5 py-1.5 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100 mt-2 inline-block"
                >
                  watch live &rarr;
                </Link>
              </div>
            </div>
          )}

          {/* Selected scan: failed */}
          {selectedScan && !selectedReport && selectedScan.status === "failed" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <p className="text-sm text-destructive mb-1">Scan failed</p>
                <p className="text-xs text-muted-foreground">
                  {selectedScan.error || "Something went wrong. Try deploying again."}
                </p>
              </div>
            </div>
          )}

          {/* Selected scan: completed, no report (edge case) */}
          {selectedScan && !selectedReport && selectedScan.status === "completed" && (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-muted-foreground">No report generated for this scan.</p>
            </div>
          )}

          {/* Report view */}
          {selectedReport && (
            <>
              {/* Report header */}
              <div className="px-6 py-4 border-b border-border shrink-0">
                <div className="flex items-baseline justify-between mb-1">
                  <div className="flex items-baseline gap-4">
                    <h2 className="text-sm font-semibold">
                      {selectedScan ? getScanLabel(selectedScan) : "Report"}
                    </h2>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {new Date(selectedReport.createdAt).toLocaleString()}
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    <Link
                      href={`/projects/${projectId}/scan/${effectiveSelectedId}`}
                      className="text-xs border border-rem/30 text-rem/70 px-2.5 py-1 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100"
                    >
                      trace &rarr;
                    </Link>
                  </div>
                </div>
                <div className="flex items-baseline gap-3 text-xs text-muted-foreground tabular-nums mt-1">
                  <span>{selectedReport.findings.length} findings</span>
                  {(["critical", "high", "medium", "low", "info"] as const).map((sev) => {
                    const count = selectedReport.findings.filter((f) => f.severity === sev).length;
                    if (count === 0) return null;
                    return (
                      <span
                        key={sev}
                        className={sev === "critical" || sev === "high" ? "text-destructive" : ""}
                      >
                        {count} {sev}
                      </span>
                    );
                  })}
                </div>
              </div>

              {/* Report body — scrollable */}
              <div className="flex-1 overflow-y-auto">
                <div className="px-6 py-5">
                  {selectedReport.summary && (
                    <p className="text-sm text-muted-foreground leading-relaxed text-justify mb-6 pb-5 border-b border-border ">
                      {selectedReport.summary}
                    </p>
                  )}

                  {selectedReport.findings.map((finding, i) => {
                    const sevBorder =
                      finding.severity === "critical" ? "border-l-destructive" :
                      finding.severity === "high" ? "border-l-destructive/60" :
                      finding.severity === "medium" ? "border-l-rem/50" :
                      finding.severity === "low" ? "border-l-rem/25" :
                      "border-l-border";

                    return (
                      <div
                        key={i}
                        className={`py-5 px-5 mb-3 border border-border border-l-[3px] ${sevBorder} bg-card/30 animate-fade-slide-in`}
                        style={{ animationDelay: `${i * 30}ms` }}
                      >
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
                              <span className="text-xs text-muted-foreground">{finding.location}</span>
                            </>
                          )}
                        </div>

                        <div className="text-sm font-medium mb-2">{finding.title}</div>

                        <p className="text-sm text-muted-foreground leading-relaxed text-justify">
                          {finding.description}
                        </p>

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
            </>
          )}
        </div>
      </div>
    </div>
  );
}
