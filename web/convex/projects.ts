import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const list = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("projects")
      .withIndex("by_user_and_status", (q) =>
        q.eq("userId", args.userId).eq("status", "active")
      )
      .order("desc")
      .collect();
  },
});

export const get = query({
  args: { projectId: v.id("projects") },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.projectId);
  },
});

export const create = mutation({
  args: {
    userId: v.id("users"),
    name: v.string(),
    targetType: v.union(
      v.literal("oss"),
      v.literal("web"),
      v.literal("hardware"),
      v.literal("fpga")
    ),
    targetConfig: v.any(),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("projects", {
      ...args,
      status: "active",
      createdAt: Date.now(),
    });
  },
});

export const updateTargetConfig = mutation({
  args: {
    projectId: v.id("projects"),
    targetConfig: v.any(),
  },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.projectId, { targetConfig: args.targetConfig });
  },
});

export const archive = mutation({
  args: { projectId: v.id("projects") },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.projectId, { status: "archived" });
  },
});
