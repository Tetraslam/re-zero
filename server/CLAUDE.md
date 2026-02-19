# Server — Re:Zero

## What this is
Stateless FastAPI server that orchestrates Modal sandboxes for security scanning agents, relays agent actions to Convex, and manages hardware gateways. All persistent state lives in Convex.

## Package management
- **uv only**. Never use pip. Never manually edit pyproject.toml for package versions.
- `uv add <package>` / `uv remove <package>` / `uv sync`

## Running
```bash
uv run uvicorn main:app --reload
```

## Architecture
```
server/
├── main.py              # FastAPI app, CORS, routers
├── app/
│   ├── config.py        # Settings from .env (Convex URL, deploy key, Modal tokens)
│   ├── convex_client.py # HTTP client for calling Convex mutations/queries
│   ├── routers/
│   │   ├── scans.py     # POST /scans/launch, /scans/start, /scans/action, /scans/report, /scans/verify
│   │   ├── gate.py      # POST /gate/scan (synchronous Haiku gate scan on diffs)
│   │   └── gateways.py  # POST /gateways/heartbeat
│   ├── lib/
│   │   ├── anthropic_client.py  # Shared Anthropic/Bedrock client factory
│   │   └── autumn.py    # Autumn billing: autumn_check, autumn_track
│   └── sandbox/
│       └── orchestrator.py  # Modal functions: run_oss_scan, run_web_scan
```

## Scan modes

### OSS (source code)
- Modal function: `run_oss_scan`
- Image: `sandbox_image` (debian + git + httpx/anthropic)
- Flow: clone repo → Claude agent reads/searches files → submit findings
- Tools: `read_file`, `search_code`, `submit_findings` + Firecrawl MCP

### Web (pentesting)
- Modal function: `run_web_scan`
- Image: `web_sandbox_image` (debian + Playwright/Chromium + Stagehand)
- Flow: launch headless Chrome → Claude agent browses/tests target → submit findings
- Tools: `navigate`, `observe`, `act`, `extract`, `execute_js`, `screenshot`, `submit_findings` + Firecrawl MCP
- Browser: Stagehand (server=local, Haiku for element resolution) → Playwright via CDP for raw JS/screenshots (all in Modal container, no external browser service)
- Screenshots: uploaded to Convex file storage via `storage:generateUploadUrl` mutation, storageId stored in action payload
- Auth: if test account provided, scans both unauthenticated and authenticated surfaces
- Active testing: injects XSS/SQLi payloads, tests auth bypass, checks headers, CORS, cookies

## Key patterns
- **Stateless**: Server stores nothing locally. All state → Convex via `convex_client.py`.
- **Agent callbacks**: Agents in Modal sandboxes write directly to Convex (not back to server). Frontend subscribes via Convex reactivity.
- **Report submission**: Agents call `_submit_report()` which writes to Convex and marks scan completed.
- **MCP**: Firecrawl MCP server available to agents via Anthropic's MCP connector beta (`betas=["mcp-client-2025-11-20"]`).

## Convex integration
- Uses HTTP API (not the Convex Python SDK's real-time client) for simplicity
- Auth: `Authorization: Convex {deploy_key}` header
- Mutations: POST to `{CONVEX_URL}/api/mutation` with `{path, args}`
- Queries: POST to `{CONVEX_URL}/api/query` with `{path, args}`

## Environment variables (.env)
```
CONVEX_URL=https://steady-mosquito-754.convex.cloud
CONVEX_DEPLOY_KEY=<from convex dashboard>
```

## Rules
- Never use pip
- Never manually edit pyproject.toml dependency versions
- Never commit .env
- All state goes to Convex, never local storage
- Keep routers thin — business logic in dedicated modules
