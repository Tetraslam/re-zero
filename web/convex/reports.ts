import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const getByScan = query({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("reports")
      .withIndex("by_scan", (q) => q.eq("scanId", args.scanId))
      .unique();
  },
});

export const listByProject = query({
  args: { projectId: v.id("projects") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("reports")
      .withIndex("by_project", (q) => q.eq("projectId", args.projectId))
      .order("desc")
      .collect();
  },
});

export const submit = mutation({
  args: {
    scanId: v.id("scans"),
    projectId: v.id("projects"),
    findings: v.array(
      v.object({
        id: v.optional(v.string()),
        title: v.string(),
        severity: v.union(
          v.literal("critical"),
          v.literal("high"),
          v.literal("medium"),
          v.literal("low"),
          v.literal("info")
        ),
        description: v.string(),
        location: v.optional(v.string()),
        recommendation: v.optional(v.string()),
        codeSnippet: v.optional(v.string()),
      })
    ),
    summary: v.optional(v.string()),
    raw: v.optional(v.any()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("reports", {
      ...args,
      createdAt: Date.now(),
    });
  },
});
