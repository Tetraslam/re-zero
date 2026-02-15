import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const create = mutation({
  args: {
    scanId: v.id("scans"),
    question: v.string(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("prompts", {
      scanId: args.scanId,
      question: args.question,
      status: "pending",
      createdAt: Date.now(),
    });
  },
});

export const respond = mutation({
  args: {
    promptId: v.id("prompts"),
    response: v.string(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.promptId, {
      response: args.response,
      status: "answered",
      answeredAt: Date.now(),
    });
  },
});

export const get = query({
  args: { promptId: v.id("prompts") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.promptId);
  },
});

export const getPendingByScan = query({
  args: { scanId: v.id("scans") },
  handler: async (ctx, args) => {
    const prompts = await ctx.db
      .query("prompts")
      .withIndex("by_scan", (q) => q.eq("scanId", args.scanId))
      .collect();
    return prompts.filter((p) => p.status === "pending");
  },
});
