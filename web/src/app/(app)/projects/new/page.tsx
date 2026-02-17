"use client";

import { useState } from "react";
import { useMutation } from "convex/react";
import { api } from "../../../../../convex/_generated/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useRouter } from "next/navigation";
import Link from "next/link";

const TARGET_TYPES = [
  { value: "oss" as const, label: "Source code", description: "Clone and audit a public GitHub repository" },
  { value: "web" as const, label: "Web application", description: "Browser-based pentesting of a live URL" },
];

type TargetType = "oss" | "web";

export default function NewProjectPage() {
  const { user } = useCurrentUser();
  const createProject = useMutation(api.projects.create);
  const router = useRouter();

  const [name, setName] = useState("");
  const [targetType, setTargetType] = useState<TargetType | null>(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [webUrl, setWebUrl] = useState("");
  const [webUsername, setWebUsername] = useState("");
  const [webPassword, setWebPassword] = useState("");
  const [webContext, setWebContext] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!user || !targetType || !name.trim()) return;
    setSubmitting(true);

    let targetConfig: Record<string, unknown> = {};
    if (targetType === "oss") targetConfig = { repoUrl };
    if (targetType === "web") targetConfig = {
      url: webUrl,
      ...(webUsername ? { testAccount: { username: webUsername, password: webPassword } } : {}),
      ...(webContext.trim() ? { context: webContext.trim() } : {}),
    };
    const id = await createProject({
      userId: user._id,
      name: name.trim(),
      targetType,
      targetConfig,
    });

    router.push(`/projects/${id}`);
  };

  return (
    <div className="px-8 py-8 max-w-lg mx-auto">
      <div className="flex items-baseline gap-2 mb-8">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:text-rem transition-colors duration-150">
          projects
        </Link>
        <span className="text-xs text-muted-foreground/30">/</span>
        <span className="text-sm font-semibold">new project</span>
      </div>
      <p className="text-sm text-muted-foreground mb-10">
        Define an attack surface for Rem to analyze.
      </p>

      <div className="space-y-10">
        {/* Name */}
        <div>
          <label htmlFor="name" className="text-xs text-muted-foreground block mb-3">
            Project name
          </label>
          <input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-security-audit"
            className="w-full text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
          />
        </div>

        {/* Target type */}
        <div>
          <label className="text-xs text-muted-foreground block mb-3">
            Attack surface
          </label>
          <div className="grid grid-cols-2 gap-3">
            {TARGET_TYPES.map((t) => (
              <button
                key={t.value}
                onClick={() => setTargetType(t.value)}
                className={`border text-left p-4 transition-all duration-100 ${
                  targetType === t.value
                    ? "border-rem bg-rem/8"
                    : "border-border hover:border-rem/40 hover:bg-accent/40"
                }`}
              >
                <div className="text-sm font-medium">{t.label}</div>
                <div className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
                  {t.description}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Conditional fields */}
        {targetType === "oss" && (
          <div>
            <label htmlFor="repo" className="text-xs text-muted-foreground block mb-3">
              Repository URL
            </label>
            <input
              id="repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/org/repo"
              className="w-full text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
            />
          </div>
        )}

        {targetType === "web" && (
          <div className="space-y-6">
            <div>
              <label htmlFor="url" className="text-xs text-muted-foreground block mb-3">
                Target URL
              </label>
              <input
                id="url"
                value={webUrl}
                onChange={(e) => setWebUrl(e.target.value)}
                placeholder="https://example.com"
                className="w-full text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-3">
                Test credentials <span className="text-muted-foreground/40">— optional</span>
              </label>
              <p className="text-xs text-muted-foreground/60 mb-3">
                Provide a test account so Rem can scan authenticated surfaces. Rem will test both unauthenticated and authenticated attack surfaces.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <input
                  value={webUsername}
                  onChange={(e) => setWebUsername(e.target.value)}
                  placeholder="username or email"
                  className="text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
                />
                <input
                  type="password"
                  value={webPassword}
                  onChange={(e) => setWebPassword(e.target.value)}
                  placeholder="password"
                  className="text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150"
                />
              </div>
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-3">
                Context for Rem <span className="text-muted-foreground/40">— optional</span>
              </label>
              <textarea
                value={webContext}
                onChange={(e) => setWebContext(e.target.value)}
                placeholder={"e.g. \"There's a hidden /admin route not in the sitemap. The app uses JWT stored in localStorage. Try the GraphQL endpoint at /api/graphql.\""}
                rows={3}
                className="w-full text-sm bg-transparent border border-border px-3 py-2.5 placeholder:text-muted-foreground/40 focus:outline-none focus:border-rem transition-colors duration-150 resize-y"
              />
              <p className="text-xs text-muted-foreground/40 mt-1.5">
                Anything Rem should know — hidden routes, tech stack, areas of concern, how to use the test account.
              </p>
            </div>
          </div>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={!name.trim() || !targetType || submitting}
          className="w-full text-sm bg-rem text-white py-2.5 hover:brightness-110 transition-all duration-150 disabled:opacity-30 active:translate-y-px"
        >
          {submitting ? "Creating..." : "Create project & deploy Rem"}
        </button>
      </div>
    </div>
  );
}
