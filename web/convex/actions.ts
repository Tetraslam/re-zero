import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const listByScan = query({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("actions")
      .withIndex("by_scan", (q) => q.eq("scanId", args.scanId))
      .order("asc")
      .collect();
  },
});

export const push = mutation({
  args: {
    scanId: v.id("scans"),
    type: v.union(
      v.literal("tool_call"),
      v.literal("tool_result"),
      v.literal("reasoning"),
      v.literal("observation"),
      v.literal("report"),
      v.literal("human_input_request")
    ),
    payload: v.any(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("actions", {
      ...args,
      timestamp: Date.now(),
    });
  },
});
