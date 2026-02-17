"use client";

import { useQuery } from "convex/react";
import { api } from "../../../../convex/_generated/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import Link from "next/link";
import { useMinLoading } from "@/hooks/use-min-loading";

export default function DashboardPage() {
  const { user, isLoaded } = useCurrentUser();
  const projects = useQuery(
    api.projects.list,
    user ? { userId: user._id } : "skip"
  );

  const minTime = useMinLoading();

  if (!isLoaded || !minTime) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <div className="text-center">
          <img src="/rem-running.gif" alt="Rem" className="w-16 h-16 mx-auto mb-3 object-contain" />
          <p className="text-sm text-muted-foreground">Rem is fetching your projects...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="px-8 py-8 max-w-5xl mx-auto">
      <div className="flex items-baseline justify-between mb-10">
        <h1 className="text-sm font-semibold">projects</h1>
        <Link
          href="/projects/new"
          className="text-xs border border-rem/30 text-rem/70 px-2.5 py-1.5 hover:bg-rem/10 hover:border-rem hover:text-rem transition-all duration-100 active:translate-y-px"
        >
          + new project
        </Link>
      </div>

      {projects && projects.length === 0 && (
        <div className="py-24 text-center">
          <img src="/rem-running.gif" alt="Rem" className="w-20 h-20 mx-auto mb-4 object-contain" />
          <p className="text-sm text-foreground mb-1">
            Rem is ready to hunt.
          </p>
          <p className="text-xs text-muted-foreground mb-4">
            Give her an attack surface and she&apos;ll find what&apos;s hiding.
          </p>
          <Link
            href="/projects/new"
            className="text-sm text-rem hover:underline"
          >
            Create your first project
          </Link>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div>
          {/* Column headers */}
          <div className="flex items-baseline gap-4 pb-3 border-b border-border text-xs text-muted-foreground">
            <span className="flex-1">name</span>
            <span className="w-20">type</span>
            <span className="w-56 hidden sm:block">target</span>
            <span className="w-24 text-right">created</span>
          </div>

          {/* Rows */}
          {projects.map((project) => (
            <Link
              key={project._id}
              href={`/projects/${project._id}`}
              className="group flex items-baseline gap-4 py-3.5 border-b border-border border-l-2 border-l-transparent hover:border-l-rem hover:bg-accent/40 transition-all duration-100 -mx-3 px-3"
            >
              <span className="flex-1 text-sm font-medium group-hover:underline truncate">
                {project.name}
              </span>
              <span className="w-20 text-xs text-muted-foreground">
                {project.targetType}
              </span>
              <span className="w-56 text-xs text-muted-foreground truncate hidden sm:block">
                {project.targetType === "oss" && project.targetConfig?.repoUrl}
                {project.targetType === "web" && project.targetConfig?.url}
              </span>
              <span className="w-24 text-xs text-muted-foreground text-right tabular-nums">
                {new Date(project.createdAt).toLocaleDateString()}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
