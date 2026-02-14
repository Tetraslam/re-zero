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
│   │   ├── scans.py     # POST /scans/start, /scans/action, /scans/report
│   │   └── gateways.py  # POST /gateways/heartbeat
│   └── sandbox/
│       └── (orchestrator, agent harnesses — TODO)
```

## Key patterns
- **Stateless**: Server stores nothing locally. All state → Convex via `convex_client.py`.
- **Agent callbacks**: Agents in Modal sandboxes call POST /scans/action to report per-action updates. Server writes to Convex. Frontend subscribes via Convex reactivity.
- **Report submission**: Agents call POST /scans/report with structured findings JSON. Server writes to Convex and marks scan as completed.

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
