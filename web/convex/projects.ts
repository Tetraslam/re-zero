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

export const getLastScanDate = query({
  args: {
    userId: v.id("users"),
    repoUrl: v.string(),
  },
  handler: async (ctx, args) => {
    // Find project by repoUrl (same pattern as findOrCreate)
    const projects = await ctx.db
      .query("projects")
      .withIndex("by_user_and_status", (q) =>
        q.eq("userId", args.userId).eq("status", "active")
      )
      .collect();

    const project = projects.find(
      (p) => p.targetConfig?.repoUrl === args.repoUrl
    );
    if (!project) return null;

    // Find most recent completed scan
    const scans = await ctx.db
      .query("scans")
      .withIndex("by_project", (q) => q.eq("projectId", project._id))
      .order("desc")
      .collect();

    const lastCompleted = scans.find((s) => s.status === "completed");
    if (!lastCompleted) return { lastScanAt: null };

    return {
      lastScanAt: lastCompleted.finishedAt ?? lastCompleted.startedAt,
    };
  },
});

export const findOrCreate = mutation({
  args: {
    userId: v.id("users"),
    repoUrl: v.string(),
    targetType: v.union(
      v.literal("oss"),
      v.literal("web"),
      v.literal("hardware"),
      v.literal("fpga")
    ),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("projects")
      .withIndex("by_user_and_status", (q) =>
        q.eq("userId", args.userId).eq("status", "active")
      )
      .collect();

    const match = existing.find(
      (p) => p.targetConfig?.repoUrl === args.repoUrl
    );
    if (match) return match._id;

    const urlParts = args.repoUrl.replace(/\.git$/, "").split("/");
    const name = urlParts.slice(-2).join("/");

    return await ctx.db.insert("projects", {
      userId: args.userId,
      name,
      targetType: args.targetType,
      targetConfig: { repoUrl: args.repoUrl },
      status: "active",
      createdAt: Date.now(),
    });
  },
});
