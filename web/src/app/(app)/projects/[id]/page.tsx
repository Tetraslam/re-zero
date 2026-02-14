"use client";

import { useParams } from "next/navigation";
import { useQuery, useMutation } from "convex/react";
import { api } from "../../../../../convex/_generated/api";
import { Id } from "../../../../../convex/_generated/dataModel";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Play } from "lucide-react";

const AGENT_LABELS: Record<string, string> = {
  opus: "Opus 4.6",
  glm47v: "GLM-4.7V",
  nemotron: "Nemotron",
};

const STATUS_COLORS: Record<string, string> = {
  queued: "text-yellow-600 dark:text-yellow-400",
  running: "text-blue-600 dark:text-blue-400",
  completed: "text-emerald-600 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
};

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id as Id<"projects">;

  const project = useQuery(api.projects.get, { projectId });
  const scans = useQuery(api.scans.listByProject, { projectId });
  const reports = useQuery(api.reports.listByProject, { projectId });
  const createScan = useMutation(api.scans.create);

  const [starting, setStarting] = useState(false);

  const handleStartScan = async (agent: "opus" | "glm47v" | "nemotron") => {
    if (!project) return;
    setStarting(true);

    const scanId = await createScan({ projectId, agent });

    // Trigger the server to spin up the sandbox
    try {
      await fetch(`${process.env.NEXT_PUBLIC_SERVER_URL}/scans/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scan_id: scanId,
          project_id: projectId,
          target_type: project.targetType,
          target_config: project.targetConfig,
          agent,
        }),
      });
    } catch (err) {
      console.error("Failed to start scan:", err);
    }

    setStarting(false);
  };

  if (!project) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <p className="text-sm text-muted-foreground font-mono">Loading project...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{project.name}</h1>
        <p className="text-sm text-muted-foreground font-mono mt-1">
          {project.targetType} &middot; {new Date(project.createdAt).toLocaleDateString()}
        </p>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">Scans</h2>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleStartScan("opus")}
              disabled={starting}
            >
              <Play className="h-3 w-3 mr-1" />
              Opus 4.6
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleStartScan("glm47v")}
              disabled={starting}
            >
              <Play className="h-3 w-3 mr-1" />
              GLM-4.7V
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleStartScan("nemotron")}
              disabled={starting}
            >
              <Play className="h-3 w-3 mr-1" />
              Nemotron
            </Button>
          </div>
        </div>

        {scans && scans.length === 0 && (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No scans yet. Start one above.
          </p>
        )}

        <div className="space-y-2">
          {scans?.map((scan) => (
            <Link
              key={scan._id}
              href={`/projects/${projectId}/scan/${scan._id}`}
              className="flex items-center justify-between border border-border rounded-lg px-4 py-3 hover:bg-accent/50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className={`text-xs font-mono ${STATUS_COLORS[scan.status]}`}>
                  {scan.status}
                </span>
                <Badge variant="outline" className="text-xs font-mono">
                  {AGENT_LABELS[scan.agent]}
                </Badge>
              </div>
              <span className="text-xs text-muted-foreground">
                {new Date(scan.startedAt).toLocaleString()}
              </span>
            </Link>
          ))}
        </div>
      </div>

      {reports && reports.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-sm font-medium">Reports</h2>
          {reports.map((report) => (
            <div
              key={report._id}
              className="border border-border rounded-lg p-4 space-y-3"
            >
              {report.summary && (
                <p className="text-sm">{report.summary}</p>
              )}
              <div className="flex gap-2">
                {["critical", "high", "medium", "low", "info"].map((sev) => {
                  const count = report.findings.filter((f) => f.severity === sev).length;
                  if (count === 0) return null;
                  return (
                    <Badge key={sev} variant="outline" className="text-xs font-mono">
                      {count} {sev}
                    </Badge>
                  );
                })}
              </div>
              <div className="space-y-2">
                {report.findings.map((finding, i) => (
                  <div key={i} className="text-sm border-l-2 border-border pl-3">
                    <div className="font-medium">{finding.title}</div>
                    <div className="text-muted-foreground text-xs mt-0.5">
                      {finding.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
