"use client";

import { useQuery } from "convex/react";
import { api } from "../../../../convex/_generated/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Plus } from "lucide-react";

const TARGET_LABELS: Record<string, string> = {
  oss: "OSS",
  web: "Web",
  hardware: "Hardware",
  fpga: "FPGA",
};

export default function DashboardPage() {
  const { user, isLoaded } = useCurrentUser();
  const projects = useQuery(
    api.projects.list,
    user ? { userId: user._id } : "skip"
  );

  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <p className="text-sm text-muted-foreground font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
        <Link href="/projects/new">
          <Button size="sm">
            <Plus className="h-4 w-4 mr-1" />
            New project
          </Button>
        </Link>
      </div>

      {projects && projects.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-sm">No projects yet.</p>
          <Link href="/projects/new">
            <Button variant="outline" size="sm" className="mt-4">
              Create your first project
            </Button>
          </Link>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects?.map((project) => (
          <Link
            key={project._id}
            href={`/projects/${project._id}`}
            className="block border border-border rounded-lg p-4 hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-start justify-between">
              <h2 className="font-medium text-sm">{project.name}</h2>
              <Badge variant="outline" className="text-xs font-mono">
                {TARGET_LABELS[project.targetType]}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 font-mono truncate">
              {project.targetType === "oss" && project.targetConfig?.repoUrl}
              {project.targetType === "web" && project.targetConfig?.url}
              {project.targetType === "hardware" && project.targetConfig?.device}
              {project.targetType === "fpga" && "FPGA side-channel"}
            </p>
            <p className="text-xs text-muted-foreground mt-2">
              {new Date(project.createdAt).toLocaleDateString()}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
