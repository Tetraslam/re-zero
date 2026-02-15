# Re:Zero — Architecture

## System Overview

```
Browser → Next.js (Clerk auth, Convex client) → Convex (all state, real-time)
                                                     ↕
                                              Python Server (FastAPI)
                                                     ↕
                                              Modal Sandboxes
                                          ┌──────────┴──────────┐
                                    Claude Agent SDK      OpenCode SDK
                                      (Opus 4.6)       (GLM-4.6V / Nemotron)
```

- **Frontend:** Next.js, pnpm, Clerk auth, Convex client, shadcn (all components, fully custom theme)
- **State:** Convex handles ALL persistent state + real-time sync to frontend
- **Server:** Stateless Python/FastAPI — orchestrates Modal sandboxes, relays agent actions to Convex
- **Compute:** Modal sandboxes run agents with pre-built harnesses and tools

## Targets

### 1. OSS Repos (Code Mode)
- User provides a public GitHub repo URL
- Server spins up a Modal sandbox, clones the repo, deploys an agent
- Two agent harness options:
  - **Claude Agent SDK** — for Opus 4.6
  - **OpenCode SDK** — for GLM-4.6V (via OpenRouter) and Nemotron (via custom Modal endpoint)
- Sandbox has tools: Ghidra MCP, scratchpad, whatever else we add
- Agent explores codebase, finds vulnerabilities, writes structured JSON report
- Agent reports actions back to server via HTTP callback → server writes to Convex → frontend gets live updates

### 2. Web Pentesting
- User provides a target URL + optional test account credentials (entered in dashboard)
- Agent runs in Modal sandbox with Browserbase/Stagehand for browser automation
- Agent can log in with test account, crawl, test for vulns
- Same action reporting pipeline as OSS

### 3. Hardware (ESP32 + Drone)
- Not running in cloud — agents connect to hardware from a local machine
- **Local gateway process** runs on user's computer, communicates over serial (USB)
- Gateway exposes a standardized API that the agent can call as a tool
- Two targets for demo:
  - ESP32 with LED lights (intentionally hackable)
  - Drone (flight controller interface, camera stream)
- Frontend needs: camera feed view, serial connection status, hardware interaction log
- Gateway relays through server so Convex stays the source of truth

### 4. FPGA Side-Channel
- Extracting AES keys from power traces via FPGA (Kenneth's Genesys 2 + ChipWhisperer)
- Another local gateway, but for FPGA + ESP32 AES target setup
- The FPGA tool is janky but usable — agent triggers captures, analyzes traces
- Frontend needs: waveform visualization for power traces, capture results, key extraction progress
- This is the "holy shit" demo moment — needs to look incredible on the dashboard

## Convex Schema

```
users          — synced from Clerk (clerk_id, email, name)
projects       — name, target_type (oss|web|hardware|fpga), target_config, status, user_id
scans          — project_id, agent (opus|glm|nemotron), sandbox_id, status, started_at, finished_at
actions        — scan_id, type (tool_call|observation|reasoning|report), payload, timestamp
reports        — scan_id, findings[], severity_counts, raw JSON
gateways       — project_id, type (serial|fpga), endpoint, status, last_seen
```

**Key design choice:** The `actions` table is the real-time feed. Agents write actions to Convex via the server. Frontend subscribes with `useQuery` and gets live per-action updates. No custom WebSocket plumbing — Convex reactivity handles it.

## Server Design (FastAPI, stateless)

Three responsibilities:

### 1. Scan Orchestration
- Receives "start scan" (triggered by Convex action or direct API call)
- Spins up Modal sandbox with correct agent harness + tools for the target type
- Sandbox runs autonomously until complete

### 2. Agent Callback API
- Agents in sandboxes call back to report actions and findings
- Server validates and writes to Convex
- Final report submitted via a `submit_report` tool call from the agent

### 3. Gateway Relay
- For hardware/FPGA targets
- Bridges local gateway processes and agents
- Maintains gateway registration and heartbeats

## Agent Harness (inside Modal sandbox)

Standardized interface regardless of which SDK/model:
- Receives: task description + target config
- Has tools: Ghidra MCP, repo cloning, Browserbase/Stagehand, serial gateway client, etc.
- Reports actions: HTTP callback to our server (which writes to Convex)
- Submits report: `submit_report` tool call → structured JSON → server → Convex

## Frontend Pages

```
/                          → landing (unauthed) or redirect to dashboard
/dashboard                 → all projects, recent scans, quick stats
/projects/new              → create project wizard (pick target type → configure)
/projects/[id]             → project overview, scan history, reports
/projects/[id]/scan/[id]   → live scan view: action feed, agent reasoning, findings
/settings                  → account, API keys, gateway management
```

## UI/UX Direction

- **pnpm**, all shadcn components via `--all`
- Fully custom theme — NO generic shadcn look
- Reference: usgraphics.com aesthetic — high information density, ultra-thoughtful layout
- We're called Re:Zero — personality matters. Rem gif as loading animation. Anime flair but tasteful.
- Monospace where it counts, tight spacing, dark mode, signature accent color
- Dense data tables, minimal chrome
- Removing > adding. Keep functionality while stripping visual noise.
- Every screen should feel intentional and designed, not templated.

## Build Order

1. **Convex schema + Next.js scaffold + Clerk auth + dashboard shell** — skeleton everything hangs on
2. **Server + Modal sandbox lifecycle for OSS target** — most demo-able, end-to-end
3. **Agent harness (Claude SDK first)** — one agent actually finding vulns in a repo
4. **Live scan view** — real-time action feed (the impressive part)
5. **Web pentesting target** — add Browserbase/Stagehand
6. **Hardware/FPGA** — mostly frontend + gateway, Kenneth/William handle actual hardware
7. **Theme polish** — the personality pass, custom everything
