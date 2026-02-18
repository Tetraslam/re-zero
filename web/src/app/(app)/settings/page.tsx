"use client";

import { useQuery, useMutation } from "convex/react";
import { api } from "../../../../convex/_generated/api";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useState } from "react";
import { RemLoader } from "@/components/rem-spinner";

export default function SettingsPage() {
  const { user, isLoaded } = useCurrentUser();
  const keys = useQuery(
    api.apiKeys.listByUser,
    user ? { userId: user._id } : "skip"
  );
  const createKey = useMutation(api.apiKeys.create);
  const revokeKey = useMutation(api.apiKeys.revoke);
  const getOrCreateDefault = useMutation(api.apiKeys.getOrCreateDefault);

  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [copied, setCopied] = useState(false);
  const [creating, setCreating] = useState(false);

  if (!isLoaded) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12">
        <RemLoader />
      </div>
    );
  }

  const handleCreate = async () => {
    if (!user) return;
    setCreating(true);
    const name = newKeyName.trim() || "default";
    const key = await createKey({ userId: user._id, name });
    setNewKeyValue(key);
    setNewKeyName("");
    setCreating(false);
  };

  const handleGetDefault = async () => {
    if (!user) return;
    const key = await getOrCreateDefault({ userId: user._id });
    setNewKeyValue(key);
  };

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevoke = async (keyId: string) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await revokeKey({ keyId: keyId as any });
  };

  const activeKeys = keys?.filter((k) => !k.revokedAt) || [];
  const revokedKeys = keys?.filter((k) => k.revokedAt) || [];

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-base font-semibold mb-8">settings</h1>

      {/* API Keys Section */}
      <section>
        <p className="text-xs text-muted-foreground mb-4">API KEYS</p>
        <p className="text-sm text-muted-foreground mb-6">
          Use API keys to authenticate the CLI.{" "}
          <span className="text-foreground">npm install -g rem-scan</span>, then{" "}
          <span className="text-foreground">rem login</span>.
        </p>

        {/* Newly created key banner */}
        {newKeyValue && (
          <div className="border border-rem/30 bg-rem/5 p-4 mb-6">
            <p className="text-xs text-muted-foreground mb-2">
              Save this key now — you won&apos;t see it again.
            </p>
            <div className="flex items-center gap-2">
              <code className="text-sm font-mono flex-1 break-all">
                {newKeyValue}
              </code>
              <button
                onClick={() => handleCopy(newKeyValue)}
                className="text-xs border border-border px-2 py-1 hover:border-rem/30 transition-colors duration-100 shrink-0"
              >
                {copied ? "copied" : "copy"}
              </button>
            </div>
            <button
              onClick={() => setNewKeyValue(null)}
              className="text-xs text-muted-foreground mt-2 hover:text-foreground transition-colors duration-100"
            >
              dismiss
            </button>
          </div>
        )}

        {/* Active keys list */}
        {activeKeys.length > 0 ? (
          <div className="border border-border divide-y divide-border mb-6">
            {activeKeys.map((k) => (
              <div
                key={k._id}
                className="flex items-center justify-between px-3 py-2"
              >
                <div className="flex items-center gap-4">
                  <code className="text-xs text-muted-foreground font-mono">
                    {k.prefix}...
                  </code>
                  <span className="text-sm">{k.name}</span>
                  {k.lastUsedAt && (
                    <span className="text-xs text-muted-foreground">
                      used{" "}
                      {new Date(k.lastUsedAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => handleRevoke(k._id)}
                  className="text-xs text-destructive/70 hover:text-destructive transition-colors duration-100"
                >
                  revoke
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="border border-border px-3 py-6 text-center mb-6">
            <p className="text-sm text-muted-foreground mb-3">
              No API keys yet.
            </p>
            <button
              onClick={handleGetDefault}
              className="text-sm border border-rem/30 text-rem px-3 py-1 hover:bg-rem/5 transition-colors duration-100"
            >
              generate default key
            </button>
          </div>
        )}

        {/* Create new key */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="key name (optional)"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            className="text-sm border border-border bg-transparent px-2 py-1 flex-1 focus:border-rem focus:outline-none transition-colors duration-100 placeholder:text-muted-foreground/50"
          />
          <button
            onClick={handleCreate}
            disabled={creating}
            className="text-sm border border-rem/30 text-rem px-3 py-1 hover:bg-rem/5 transition-colors duration-100 disabled:opacity-50 shrink-0"
          >
            {creating ? "creating..." : "create key"}
          </button>
        </div>

        {/* Revoked keys */}
        {revokedKeys.length > 0 && (
          <div className="mt-8">
            <p className="text-xs text-muted-foreground mb-2">REVOKED</p>
            <div className="border border-border divide-y divide-border opacity-50">
              {revokedKeys.map((k) => (
                <div key={k._id} className="flex items-center gap-4 px-3 py-2">
                  <code className="text-xs text-muted-foreground font-mono line-through">
                    {k.prefix}...
                  </code>
                  <span className="text-sm line-through">{k.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
