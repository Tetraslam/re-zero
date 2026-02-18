import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const listByProject = query({
  args: { projectId: v.id("projects") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("scans")
      .withIndex("by_project", (q) => q.eq("projectId", args.projectId))
      .order("desc")
      .collect();
  },
});

export const get = query({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.scanId);
  },
});

export const create = mutation({
  args: {
    projectId: v.id("projects"),
    tier: v.union(v.literal("maid"), v.literal("oni")),
    model: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("scans", {
      projectId: args.projectId,
      tier: args.tier,
      model: args.model,
      status: "queued",
      startedAt: Date.now(),
    });
  },
});

export const generateShareToken = mutation({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    const scan = await ctx.db.get(args.scanId);
    if (!scan) throw new Error("Scan not found");
    if (scan.shareToken) return scan.shareToken;
    const token = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    await ctx.db.patch(args.scanId, { shareToken: token });
    return token;
  },
});

export const revokeShareToken = mutation({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.scanId, { shareToken: undefined });
  },
});

export const getByShareToken = query({
  args: { token: v.string() },
  handler: async (ctx, args) => {
    const scans = await ctx.db
      .query("scans")
      .withIndex("by_share_token", (q) => q.eq("shareToken", args.token))
      .collect();
    return scans[0] ?? null;
  },
});

export const updateStatus = mutation({
  args: {
    scanId: v.id("scans"),
    status: v.union(
      v.literal("queued"),
      v.literal("running"),
      v.literal("completed"),
      v.literal("failed")
    ),
    sandboxId: v.optional(v.string()),
    error: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const { scanId, ...updates } = args;
    const patch: Record<string, unknown> = { ...updates };
    if (args.status === "completed" || args.status === "failed") {
      patch.finishedAt = Date.now();
    }
    await ctx.db.patch(scanId, patch);
  },
});
