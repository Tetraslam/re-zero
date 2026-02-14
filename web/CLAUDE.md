# Web — Re:Zero

## What this is
Next.js dashboard for the Re:Zero security platform. Auth via Clerk, state via Convex (real-time), UI via shadcn (all components installed, fully custom theme).

## Package management
- **pnpm only**. Never use npm or yarn.
- `pnpm add <package>` / `pnpm remove <package>`
- shadcn components: `pnpm dlx shadcn@latest add <component>`

## Running
```bash
pnpm dev          # Next.js dev server
pnpm exec convex dev  # Convex dev (in separate terminal)
```

## Architecture
```
web/
├── src/
│   ├── app/
│   │   ├── page.tsx                    # Landing (unauthed → sign in, authed → redirect)
│   │   ├── layout.tsx                  # Root layout (Clerk + Convex + Tooltip providers)
│   │   └── (app)/                      # Authed routes
│   │       ├── layout.tsx              # App shell (header, nav, SyncUser)
│   │       ├── dashboard/page.tsx      # Project list
│   │       ├── projects/new/page.tsx   # Create project wizard
│   │       ├── projects/[id]/page.tsx  # Project detail + scans + reports
│   │       └── projects/[id]/scan/[scanId]/page.tsx  # Live scan view
│   ├── components/
│   │   ├── ui/                         # shadcn components (57 installed)
│   │   ├── convex-provider.tsx         # ConvexProviderWithClerk
│   │   └── sync-user.tsx               # Syncs Clerk user → Convex users table
│   └── hooks/
│       └── use-current-user.ts         # Returns Convex user from Clerk session
├── convex/
│   ├── schema.ts                       # Tables: users, projects, scans, actions, reports, gateways
│   ├── users.ts                        # getOrCreate, getByClerkId
│   ├── projects.ts                     # list, get, create, archive
│   ├── scans.ts                        # listByProject, get, create, updateStatus
│   ├── actions.ts                      # listByScan, push
│   └── reports.ts                      # getByScan, listByProject, submit
```

## Convex schema
- **users**: synced from Clerk (clerkId, email, name, imageUrl)
- **projects**: user's security audit projects (name, targetType, targetConfig, status)
- **scans**: individual scan runs (projectId, agent, sandboxId, status, timestamps)
- **actions**: real-time agent action feed (scanId, type, payload, timestamp)
- **reports**: structured findings (scanId, findings[], summary)
- **gateways**: hardware/FPGA gateway connections (projectId, type, endpoint, status)

## Key patterns
- **SyncUser**: On app load, syncs Clerk user to Convex users table via `getOrCreate` mutation
- **useCurrentUser**: Hook that returns the Convex user doc from the Clerk session
- **Real-time actions**: Scan page subscribes to `actions.listByScan` — Convex pushes updates automatically
- **Target types**: oss, web, hardware, fpga — each has different targetConfig shape

## UI/UX direction
- Dark mode by default
- High information density, monospace where it counts
- Custom theme — NOT generic shadcn. Personality matters (Re:Zero anime references welcome).
- Reference: usgraphics.com aesthetic
- Removing > adding. Every element should be intentional.

## Rules
- Never use npm or yarn
- Keep components small and focused
- All state in Convex — no local state for persistent data
- Use shadcn components as building blocks, customize heavily via CSS variables
- Convex queries use "skip" pattern when args aren't ready yet
