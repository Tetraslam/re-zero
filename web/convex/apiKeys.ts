import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

export const validate = query({
  args: { key: v.string() },
  handler: async (ctx, args) => {
    const apiKey = await ctx.db
      .query("apiKeys")
      .withIndex("by_key", (q) => q.eq("key", args.key))
      .unique();

    if (!apiKey || apiKey.revokedAt) {
      return { valid: false as const };
    }

    return { valid: true as const, userId: apiKey.userId };
  },
});

export const touch = mutation({
  args: { key: v.string() },
  handler: async (ctx, args) => {
    const apiKey = await ctx.db
      .query("apiKeys")
      .withIndex("by_key", (q) => q.eq("key", args.key))
      .unique();
    if (apiKey) {
      await ctx.db.patch(apiKey._id, { lastUsedAt: Date.now() });
    }
  },
});

export const getOrCreateDefault = mutation({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("apiKeys")
      .withIndex("by_user", (q) => q.eq("userId", args.userId))
      .collect();

    const active = existing.find((k) => !k.revokedAt);
    if (active) return active.key;

    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const hex = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const key = `re0_${hex}`;

    await ctx.db.insert("apiKeys", {
      userId: args.userId,
      key,
      name: "default",
      createdAt: Date.now(),
    });

    return key;
  },
});

export const create = mutation({
  args: {
    userId: v.id("users"),
    name: v.string(),
  },
  handler: async (ctx, args) => {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const hex = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const key = `re0_${hex}`;

    await ctx.db.insert("apiKeys", {
      userId: args.userId,
      key,
      name: args.name,
      createdAt: Date.now(),
    });

    return key;
  },
});

export const listByUser = query({
  args: { userId: v.id("users") },
  handler: async (ctx, args) => {
    const keys = await ctx.db
      .query("apiKeys")
      .withIndex("by_user", (q) => q.eq("userId", args.userId))
      .collect();

    return keys.map((k) => ({
      _id: k._id,
      name: k.name,
      prefix: k.key.slice(0, 8),
      lastUsedAt: k.lastUsedAt,
      createdAt: k.createdAt,
      revokedAt: k.revokedAt,
    }));
  },
});

export const revoke = mutation({
  args: { keyId: v.id("apiKeys") },
  handler: async (ctx, args) => {
    await ctx.db.patch(args.keyId, { revokedAt: Date.now() });
  },
});
