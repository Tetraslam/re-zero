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
- **reports**: structured findings (scanId, findings[] with optional id like VN-001, summary)
- **gateways**: hardware/FPGA gateway connections (projectId, type, endpoint, status)
- **_storage**: file storage for screenshots (web scan screenshots uploaded via `storage:generateUploadUrl`)

## Key patterns
- **SyncUser**: On app load, syncs Clerk user to Convex users table via `getOrCreate` mutation
- **useCurrentUser**: Hook that returns the Convex user doc from the Clerk session
- **Real-time actions**: Scan page subscribes to `actions.listByScan` — Convex pushes updates automatically
- **Target types**: oss, web, hardware, fpga — each has different targetConfig shape
- **Rem**: The agent is named "Rem" everywhere in the UI. "Deploy Rem", "Rem is working...", "Rem (Opus 4.6)".
- **Finding IDs**: Each finding gets a sequential VN-XXX ID assigned by the orchestrator before saving to Convex.
- **Turn grouping**: Scan page groups flat actions into turns (each reasoning block starts a new turn).
- **Multi-report**: One project has many scans, each scan has one report. Project page joins reports to scans via reportByScan map.
- **Screenshots**: Web scans store screenshots in Convex file storage. Action payloads with `storageId` render as inline images via `ScreenshotImage` component (uses `storage:getUrl` query).
- **Web scan tools**: navigate, observe, act, extract, execute_js, screenshot, submit_findings (vs OSS: read_file, search_code, submit_findings)

## Brand & design system

**Concept**: Re:Zero = "Return from zero." Named after the anime where the protagonist iterates through death, accumulating knowledge. For security: agents probe, fail, learn, return. Each scan is a "life." The agent is named **Rem** (from Re:Zero).

**Palette**: Midnight navy base + rem blue (action) + red (danger). Three-color hierarchy.
- Light: #f7f7fc bg, #111428 text, #d6d8e6 borders
- Dark: #0c0e1a bg, #cfd2e3 text, #222645 borders
- Rem blue (#4f68e8 light / #6b82ff dark): THE interactive color. All CTAs, hovers, focus states, active indicators, tool badges, reasoning borders, turn headers, scroll progress, selection highlights, severity medium/low bars.
- Red/destructive (#c53528 light / #dc4242 dark): ONLY for critical/high severity and the brand colon in "re:zero"
- Visual hierarchy: navy (ground) → silver (content) → rem blue (action/alive) → red (danger/severity)

**Color usage rules**:
- CTA/primary buttons: `bg-rem text-white`, never `bg-foreground`
- Nav/link hovers: `hover:text-rem`, never `hover:text-foreground`
- Input focus: `focus:border-rem`, never `focus:border-foreground`
- Selected/active cards: `border-rem bg-rem/8`, never `border-foreground bg-accent`
- Row hovers: `border-l-2 border-l-transparent hover:border-l-rem` for the slide-in left accent
- Running scan rows: `border-l-2 border-l-rem` (always visible, Rem is active)
- Reasoning borders: `border-rem/25` (Rem's thinking)
- Recommendations: `border-rem/30` (Rem's advice)
- Turn headers: `text-rem/40` (Rem's label)
- Tool badges: `text-rem/70 border-rem/20`
- Brand line pulses rem blue during scans (switches from red to `--rem`)

**Typography**: Geist Mono as body font. Hierarchy through weight + size, not color.
- Page titles: text-base font-semibold
- Section labels: text-xs text-muted-foreground
- Body: text-sm
- Metadata: text-xs tabular-nums

**Shape**: 1px border radius everywhere. Sharp corners. No rounded anything.

**Space**: Intentional vertical rhythm. Generous spacing between sections (mb-12), tight within (gap-3). Space IS the design.

**Texture**:
- Film grain / CRT noise overlay via SVG feTurbulence (body::after, 4% opacity, animated)
- Brand line (2px red) at viewport top (body::before) — switches to rem blue and pulses when scan is running (body.scanning class)

**Microinteractions**:
- RemSpinner: terminal pipe spinner (| / — \) cycling at 120ms — used in trace panel header and loading states
- BlinkingCursor: 1.5x3.5px rem blue block with CSS step-end blink — shown at end of latest reasoning
- Staggered entry: findings animate in with 50ms delay between each (fadeSlideIn keyframe)
- Scroll progress: 1px rem blue bar in trace panel header showing scroll position
- Severity bar: 3px proportional colored segments showing finding distribution
- Turn headers: "TURN 01 ————— 00:19:45" separators in trace
- Brand pulse: body::before opacity breathes when body.scanning is active
- Duration transitions: 100ms for interactive (snappy), 150ms for navigation (deliberate)
- active:translate-y-px for press feedback

**Decoration rules**:
- 2px red brand line at viewport top (switches to rem blue during scans)
- Left borders (border-l-2) in rem blue for reasoning blocks, recommendations, and active row indicators
- Horizontal rules between sections
- No gradients, no shadows, no glows, no icons (Lucide icons banned from app pages)
- Noise texture on everything

**Layout**:
- Scan page is full viewport width (no max-w constraint)
- Other pages self-constrain (max-w-5xl or max-w-lg)
- App layout provides only header + flex-1 main — pages handle their own padding

**Primary reference**: usgraphics.com (dark-dominant, catalog-numbering, CRT/technical-manual aesthetic)

## Rules
- Never use npm or yarn
- Keep components small and focused
- All state in Convex — no local state for persistent data
- Use shadcn components as building blocks, customize heavily via CSS variables
- Convex queries use "skip" pattern when args aren't ready yet
- Agent is always "Rem" in UI context, never "agent"
- Finding IDs are VN-XXX format, assigned by orchestrator
