export const TIER_CONFIG = {
  maid: {
    label: "Maid",
    price: 25,
    defaultModel: "claude-sonnet-4.6",
    models: {
      "claude-sonnet-4.6": { label: "Sonnet 4.6" },
      "glm-5": { label: "GLM-5" },
    },
  },
  oni: {
    label: "Oni",
    price: 45,
    defaultModel: "claude-opus-4.6",
    models: {
      "claude-opus-4.6": { label: "Opus 4.6" },
      "kimi-k2.5": { label: "Kimi K2.5" },
    },
  },
} as const;

export type Tier = keyof typeof TIER_CONFIG;
export const DEFAULT_TIER: Tier = "maid";

export function getScanLabel(scan: {
  tier?: string;
  model?: string;
}): string {
  const cfg = TIER_CONFIG[scan.tier as Tier];
  if (!cfg) return "Rem";
  const modelLabel = scan.model
    ? (cfg.models as Record<string, { label: string }>)[scan.model]?.label
    : null;
  return `Rem (${cfg.label}${modelLabel ? ` \u00b7 ${modelLabel}` : ""})`;
}

export function getScanShort(scan: {
  tier?: string;
}): string {
  const cfg = TIER_CONFIG[scan.tier as Tier];
  return cfg?.label ?? "?";
}
