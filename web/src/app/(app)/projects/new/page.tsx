"use client";

import { useState } from "react";
import { useMutation } from "convex/react";
import { api } from "../../../../../convex/_generated/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const TARGET_TYPES = [
  { value: "oss" as const, label: "OSS Repo", description: "Scan a public GitHub repository for vulnerabilities" },
  { value: "web" as const, label: "Web", description: "Pentest a live website with browser automation" },
  { value: "hardware" as const, label: "Hardware", description: "Reverse engineer hardware via serial gateway" },
  { value: "fpga" as const, label: "FPGA", description: "Extract secrets via side-channel analysis" },
];

type TargetType = "oss" | "web" | "hardware" | "fpga";

export default function NewProjectPage() {
  const { user } = useCurrentUser();
  const createProject = useMutation(api.projects.create);
  const router = useRouter();

  const [name, setName] = useState("");
  const [targetType, setTargetType] = useState<TargetType | null>(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [webUrl, setWebUrl] = useState("");
  const [device, setDevice] = useState<"esp32" | "drone">("esp32");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!user || !targetType || !name.trim()) return;
    setSubmitting(true);

    let targetConfig: Record<string, unknown> = {};
    if (targetType === "oss") targetConfig = { repoUrl };
    if (targetType === "web") targetConfig = { url: webUrl };
    if (targetType === "hardware") targetConfig = { device };
    if (targetType === "fpga") targetConfig = {};

    const id = await createProject({
      userId: user._id,
      name: name.trim(),
      targetType,
      targetConfig,
    });

    router.push(`/projects/${id}`);
  };

  return (
    <div className="max-w-lg mx-auto space-y-8">
      <h1 className="text-xl font-semibold tracking-tight">New project</h1>

      <div className="space-y-2">
        <Label htmlFor="name">Project name</Label>
        <Input
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-security-audit"
          className="font-mono text-sm"
        />
      </div>

      <div className="space-y-3">
        <Label>Target type</Label>
        <div className="grid grid-cols-2 gap-3">
          {TARGET_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => setTargetType(t.value)}
              className={`border rounded-lg p-3 text-left transition-colors ${
                targetType === t.value
                  ? "border-primary bg-accent"
                  : "border-border hover:bg-accent/50"
              }`}
            >
              <div className="font-medium text-sm">{t.label}</div>
              <div className="text-xs text-muted-foreground mt-1">
                {t.description}
              </div>
            </button>
          ))}
        </div>
      </div>

      {targetType === "oss" && (
        <div className="space-y-2">
          <Label htmlFor="repo">Repository URL</Label>
          <Input
            id="repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/org/repo"
            className="font-mono text-sm"
          />
        </div>
      )}

      {targetType === "web" && (
        <div className="space-y-2">
          <Label htmlFor="url">Target URL</Label>
          <Input
            id="url"
            value={webUrl}
            onChange={(e) => setWebUrl(e.target.value)}
            placeholder="https://example.com"
            className="font-mono text-sm"
          />
        </div>
      )}

      {targetType === "hardware" && (
        <div className="space-y-3">
          <Label>Device</Label>
          <div className="flex gap-3">
            {(["esp32", "drone"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDevice(d)}
                className={`border rounded-lg px-4 py-2 text-sm font-mono transition-colors ${
                  device === d
                    ? "border-primary bg-accent"
                    : "border-border hover:bg-accent/50"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        </div>
      )}

      <Button
        onClick={handleSubmit}
        disabled={!name.trim() || !targetType || submitting}
        className="w-full"
      >
        {submitting ? "Creating..." : "Create project"}
      </Button>
    </div>
  );
}
