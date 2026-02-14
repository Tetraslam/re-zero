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
    agent: v.union(
      v.literal("opus"),
      v.literal("glm47v"),
      v.literal("nemotron")
    ),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("scans", {
      ...args,
      status: "queued",
      startedAt: Date.now(),
    });
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
