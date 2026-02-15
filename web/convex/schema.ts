import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  users: defineTable({
    clerkId: v.string(),
    email: v.string(),
    name: v.string(),
    imageUrl: v.optional(v.string()),
  }).index("by_clerk_id", ["clerkId"]),

  projects: defineTable({
    userId: v.id("users"),
    name: v.string(),
    targetType: v.union(
      v.literal("oss"),
      v.literal("web"),
      v.literal("hardware"),
      v.literal("fpga")
    ),
    // Target-specific config:
    // oss: { repoUrl: string }
    // web: { url: string, testAccount?: { username, password } }
    // hardware: { device: "esp32" | "drone", gatewayId?: Id<"gateways"> }
    // fpga: { gatewayId?: Id<"gateways"> }
    targetConfig: v.any(),
    status: v.union(
      v.literal("active"),
      v.literal("archived")
    ),
    createdAt: v.number(),
  })
    .index("by_user", ["userId"])
    .index("by_user_and_status", ["userId", "status"]),

  scans: defineTable({
    projectId: v.id("projects"),
    agent: v.union(
      v.literal("opus"),
      v.literal("glm47v"),
      v.literal("nemotron")
    ),
    sandboxId: v.optional(v.string()),
    status: v.union(
      v.literal("queued"),
      v.literal("running"),
      v.literal("completed"),
      v.literal("failed")
    ),
    startedAt: v.number(),
    finishedAt: v.optional(v.number()),
    error: v.optional(v.string()),
    shareToken: v.optional(v.string()),
  })
    .index("by_project", ["projectId"])
    .index("by_status", ["status"])
    .index("by_share_token", ["shareToken"]),

  actions: defineTable({
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
    timestamp: v.number(),
  }).index("by_scan", ["scanId", "timestamp"]),

  reports: defineTable({
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
    createdAt: v.number(),
  })
    .index("by_scan", ["scanId"])
    .index("by_project", ["projectId"]),

  prompts: defineTable({
    scanId: v.id("scans"),
    question: v.string(),
    response: v.optional(v.string()),
    status: v.union(
      v.literal("pending"),
      v.literal("answered"),
    ),
    createdAt: v.number(),
    answeredAt: v.optional(v.number()),
  }).index("by_scan", ["scanId"]),

  gateways: defineTable({
    projectId: v.id("projects"),
    type: v.union(v.literal("serial"), v.literal("fpga")),
    endpoint: v.string(),
    status: v.union(
      v.literal("online"),
      v.literal("offline")
    ),
    lastSeen: v.number(),
  }).index("by_project", ["projectId"]),
});
