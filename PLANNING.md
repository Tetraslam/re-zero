# Re:Zero Platform Planning

> Synthesized from strategic discussions, Feb 16 2026.
> Living document — update as decisions are made.

---

## Vision

**Re:Zero is an autonomous security analysis platform.** AI agents ("Rem") red-team any attack surface — source code, web apps, and beyond. One platform, multiple target types, AI-powered vulnerability discovery.

**Core thesis**: The tooling gap is the bottleneck, not model capability. Models can already find real vulnerabilities (proven: 17 findings on a live site in 21 minutes). The product is about giving the model the right tools, context, and autonomy to do what it's already capable of.

**Focus**: Web and OSS scanning only. Hardware/FPGA modes were hackathon demos — software is where the product lives.

---

## Target Market & ICP

### Phase 1: Indie Devs & AI Builders (now → 6 months)
- Solo devs shipping fast, not thinking about security
- The "vibe coder" wave — people building with AI who need security checks
- **Hook**: "I just vibe-coded this whole app, is it full of holes?"
- **Distribution**: CLI + GitHub Action, frictionless integration
- **Growth**: Find real bugs → tweet about it → organic growth

### Phase 2: Startup CTOs (6-12 months)
- "We need to pass SOC 2" / "Investor asked about security posture"
- Recurring scans, dashboards, trend tracking
- Compliance reports (PDF, SARIF)
- **Example**: Natural (where Shresht works) — CPO wants to run Rem against their product

### Phase 3: Security Teams at Mid-Market (12+ months)
- Already using Snyk/Semgrep/Burp, need the AI reasoning layer
- Slack integrations, custom scan profiles, baseline management
- Competitive landscape: Hex Security (YC), Snyk, Semgrep, etc.

### GTM Strategy
- **Bottom-up PLG**: Dev finds Rem -> scans personal project -> brings to work -> team adopts
- Dev who loves Rem at home becomes the champion who brings it to their startup. This is the Datadog/Slack/Linear playbook. Don't pitch enterprises -- your users drag you into them.
- **Build for indie devs first**, not enterprise. Don't gate features.
- PMF will reveal willingness to pay. Start at $25-45/scan, adjust as market signals come in.

---

## Business Model

### Usage-Based Pricing (Per-Scan)

No subscription. No seat fees. No credits. Pay per scan.

| Scan Depth | Our Cost (w/ caching) | Price | Margin |
|---|---|---|---|
| CI Gate (Haiku) | ~$0.04 | $0.10 | 60% |
| Standard | ~$9.50 | $25 | 62% |
| Deep | ~$16 | $45 | 64% |
| Comprehensive | ~$50-75 | $150 | 50-67% |

Volume packs via Autumn: buy 10 scans get 15% off, buy 25 get 25% off. Prepaid, no expiration.

**Principles**:
- Pure usage-based. Developers pay when they scan, not monthly.
- Security audits are episodic (before launch, after major changes, quarterly). 4-8 scans/year for indie devs = $100-360/year. Less than Cursor.
- CI gate is $0.10/scan (Haiku, ~$0.04 cost). Low enough to run on every PR, high enough to generate revenue at scale.
- Don't artificially gate features. Indie devs get CI/CD, CLI, everything.
- The user picks scan depth, not models. Model selection is internal to us.
- Margins are 50-67%. Normal for agent products (Bessemer: "AI companies see 50-60% gross margins"). Not SaaS margins, and that's fine.
- Value comparison: human pentest = $5,000-25,000. Rem deep scan = $45. That's the pitch.

### Cost Benchmarks

Based on actual usage: confirmed ~$29 per standard Opus web scan (~3.5M input + ~400K output tokens across 77 turns) without optimization.

**The cost reducer: prompt caching.** In a multi-turn agent scan, context accumulates each turn. Most input tokens are cache reads (10% of base price). With ~80% cache hit rate:

| Model | Without Caching | With Caching (~80% hits) | Reduction |
|---|---|---|---|
| Opus 4.6 | ~$29 | **~$16** | 45% |
| Sonnet 4.6 | ~$17 | **~$9.50** | 44% |
| Haiku 4.5 (CI gate) | ~$0.15 | **~$0.04** | 73% |

Cache pricing (from Anthropic docs, confirmed Feb 2026):
- Cache read = 10% of base input price (Opus: $0.50/MTok, Sonnet: $0.30/MTok, Haiku: $0.10/MTok)
- Cache write = 125% of base input price (first turn + new content each turn)
- Discounts stack with Batch API (50% off) for non-agentic subtasks

**Per-model reference (raw, no caching):**

| Model | Input $/MTok | Output $/MTok | Raw Scan Cost |
|---|---|---|---|
| Opus 4.6 | $5.00 | $25.00 | ~$29 |
| Sonnet 4.6 | $3.00 | $15.00 | ~$17 |
| Haiku 4.5 | $1.00 | $5.00 | ~$5 |
| GPT-5.2 | $1.75 | $14.00 | ~$12 |
| GPT-5-mini | $0.25 | $2.00 | ~$1.70 |

Modal (~$0.50-1/scan), Firecrawl (~$1-5/scan), Clerk/Convex: negligible vs token costs.

**API credits situation (Feb 17, 2026):** Out of $500 free Anthropic credits (hackathon grant). Claude for Startups requires VC backing through partner VCs — not accessible pre-raise.

**Solution: Amazon Bedrock via $5K AWS credits.** Bedrock pricing is IDENTICAL to Anthropic API on global endpoints — same $3/$15 for Sonnet, same $5/$25 for Opus, same prompt caching multipliers. Drop-in replacement via `AnthropicBedrock` client class in the same `anthropic` Python SDK. Same `messages.create()` API, same tool use, same streaming, same prompt caching (`cache_control`), same 1M context window.

- **$5K covers**: ~526 standard Sonnet scans, ~312 deep Opus scans, or ~125K Haiku gate scans. Months of dev + first wave of real users.
- **Implementation**: Swap `Anthropic()` for `AnthropicBedrock(aws_region="us-west-2")`, update model IDs (e.g., `global.anthropic.claude-opus-4-6-v1`). Env var toggle between direct API and Bedrock.
- **Prompt caching on Bedrock**: Fully supported. 5-min and 1-hour TTL. Same cache_control API. Same pricing: cache read = 10% of input, cache write = 125%.
- **Batch API on Bedrock**: 50% discount, same as direct API.
- **Regional vs Global**: Use global endpoints (no markup). Regional = 10% premium, only needed for data residency.
- **OpenRouter** for non-Anthropic model dev (OpenCode harness, GLM, etc.) — pay-as-you-go.
- **Claude for Startups ($25K credits)** unlocks after raising pre-seed/YC. Nice-to-have, not a dependency.
- At scale (100 scans/day on Sonnet w/ caching): ~$950/day cost, ~$2,500/day revenue at $25/scan = healthy 62% margin.

**Note:** Scan costs scale roughly linearly with turn count. Bigger apps = more turns = higher cost. The benchmarks above are based on a 77-turn scan of a medium-sized web app. A large monorepo could be 2-3x.

**Sonnet 4.6 update (Feb 17, 2026):** Sonnet 4.6 released with near-Opus performance, same $3/$15 pricing, and 1M context window. This is a major win:
- Sonnet 4.6 should be the **default model for all scan tiers** (standard AND deep), not just standard.
- 1M context = load entire codebases at once. Better cross-file reasoning, fewer tool calls.
- Opus reserved for comprehensive pentests only, or as a fallback if Sonnet quality doesn't hold on specific tasks.
- Caveat: prompts >200K tokens get 2x pricing ($6/$22.50 input/output, cache read $0.60/MTok). Smart context management still matters.
- Need to benchmark Sonnet 4.6 on security tasks ASAP -- if it matches Opus, our default scan cost drops from ~$16 to ~$9.50. Margins jump to 62-75% across the board.

### No Free Tier

**Decision: No free tier. First scan free, then pay.**

Rationale:
- Every free scan costs $9-16 in real money (with caching). No infinite runway.
- "Free" signals "toy." Security tools that matter cost money.
- Target users already spend hundreds on tokens/hosting. $25-45 for security is nothing.
- YC: "charge from day 1" and "the best way to make more money is to charge more."

**First-scan-free flow:**
1. User runs `rem scan .` -- first scan is free (deep scan, Opus, full depth)
2. Results page: full findings shown, no gating
3. Show the value upfront. "Rem found 7 vulnerabilities in 21 minutes."
4. Next scan requires payment. Conversion at the moment of need.
5. CAC: ~$16 per acquired user (one Opus scan with caching). Excellent unit economics.

### Payments
- **Autumn** (useautumn.com) for usage-based billing
- Warm intro via Mosaic (YC W25) founders → same batch as Autumn
- Alternative: Stripe (but would need to build metering layer manually)

---

## Product Architecture

### Current State (TreeHacks)
- **Frontend**: Next.js + shadcn/ui + Convex (realtime) + Clerk auth → Vercel
- **Server**: FastAPI on Railway -- stateless orchestrator
- **Compute**: Modal sandboxes (Claude Opus 4.6, GLM-4.6V via OpenCode, Nemotron)
- **Database**: Convex -- agents write directly, frontend subscribes live
- **Agent quality**: Opus >> GLM-4.6V > Nemotron (Nemotron was bad)

### What We're Adding

| Addition | What | Why |
|---|---|---|
| **Autumn** | Usage-based billing via Stripe | Per-scan metering in 3 functions. Saves weeks vs raw Stripe. PMF confirmed (T3 Chat uses them). |
| **Codex SDK** | OpenAI agent harness | Multi-provider from day 1. GPT-5.2 as scan engine. ~20 min integration. |
| **CLI** | `npx rem-scan` | New code (Node package). The primary developer interface. |
| **GitHub Action** | `rezero/scan-action` | New code. CI gate distribution. |
| **Prompt caching** | Anthropic API feature | Same SDK, different params. 45% cost reduction. |
| **Haiku/Sonnet** | Additional Claude model tiers | Same SDK, different model strings. CI gate + standard scans. |
| **Sandbox tools** | semgrep, nuclei, npm/pip/cargo audit, tree-sitter | Installed in existing Modal sandbox image. Agent tools. |

**Not adding new services.** Two new external dependencies: Autumn and OpenAI (Codex SDK). Everything else is new code on existing infra or tools in existing sandboxes.

### Railway Server: Keep for Now, Migrate Later

The FastAPI server currently exists for one meaningful route: `/scans/start` (spawn Modal function with credentials). The other routes (`/scans/action`, `/scans/report`) are redundant relays -- sandboxes already write to Convex directly.

**Plan: keep Railway for v1 launch. Migrate to Convex HTTP actions post-launch.**

Convex actions can `fetch()` a Modal web endpoint, which eliminates Railway entirely. Benefits: $0 extra cost (vs $5-15/month), built-in Clerk auth (currently the Railway routes have zero authentication), one fewer service. Requires converting Modal functions to `@modal.web_endpoint()`. Not worth doing during the product build, but a clean simplification for later.

### Agent Harness Architecture

```
ScanEngine (common tool interface, Convex reporting, finding format)
├── ClaudeAgent    -- Anthropic SDK (Opus, Sonnet, Haiku) -- primary, best quality
├── CodexAgent     -- OpenAI Codex SDK (GPT-5.2) -- TODO, ~20 min integration
└── OpenCodeAgent  -- OpenCode SDK via OpenRouter -- catch-all for everything else
```

Three harnesses, not N:
- **Anthropic SDK** -- Claude models. Primary. Best quality, prompt caching, batch API.
- **Codex SDK** -- OpenAI models. Second provider. Design their harness for their models.
- **OpenCode SDK** -- Everything else via OpenRouter. Universal catch-all. Any model on OpenRouter is automatically available: Kimi, Z-AI, MiniMax, DeepSeek, whatever comes next. No per-provider integration work.

This means we never need to build a custom harness for a provider unless they're Anthropic or OpenAI. Everyone else goes through OpenRouter. If a provider's proprietary harness isn't worth integrating (Gemini CLI, etc.), we skip it and use their model through OpenRouter instead.

Each engine gets the same tool interface. Platform picks model based on scan depth. Users never see or configure model selection. Multi-provider strategy = negotiating leverage on API pricing + best-model-for-task routing.

### Orchestrator + Subagent Paradigm
- Orchestrator agent **does real work** — reads files, traces data flows, reasons about architecture
- Delegates to subagents for context-heavy but clear-result tasks (CVE triage, endpoint fuzzing, dep scanning)
- Like a senior engineer who uses tools/agents, not a manager who only delegates
- Subagents return structured results; orchestrator synthesizes into findings
- Cheaper, more reliable, easier to debug than peer-to-peer multi-agent

---

## CLI — The Trojan Horse

### Core Commands
```bash
rem scan .                          # standard scan of current directory
rem scan --deep                     # deep scan (more thorough, higher cost)
rem scan --target https://app.com   # web scan
rem scan --repo github.com/org/repo # remote OSS scan (public)
rem scan --watch                    # rescan on git push
rem scan --dry-run                  # show what files would be uploaded + estimated cost
rem scan . --local                  # [NOT PLANNED] code never leaves machine
rem report VN-001                   # detailed finding view
rem ignore VN-003 --reason "..."    # baseline management
rem init                            # interactive setup: GitHub Action + .remignore + .rem.yml

rem login                           # authenticate
rem status                          # check scan progress
rem history                         # past scans
rem budget                          # show current month's spending vs limit
```

Users pick depth (`--deep`), not models. Model selection is internal.

### Local Repo Scanning Flow
1. CLI reads repo locally, respects `.gitignore` + `.remignore`
2. Creates filtered tarball (skip node_modules, .git, binaries, files >50KB)
3. Uploads to presigned URL (server generates → temp storage)
4. Modal sandbox downloads archive, extracts, scans
5. Archive auto-deleted after scan completes
6. Results streamed back to CLI via SSE
7. `--dry-run` to preview what gets uploaded
8. Optional confirmation step before upload (configurable, default on for first scan)

### Private Repo Support
- GitHub App integration — user connects their GitHub account
- CLI authenticates via `rem login` → gets token
- For private repos: `rem scan --repo github.com/org/private-repo` uses GitHub App token

### Distribution
- `npx rem-scan` (fastest to ship, audience has Node)
- Future: single binary (Rust/Go) for wider distribution
- Open source the CLI — distribution mechanism + community contributions

---

## GitHub Actions Integration

### CI Gate (Haiku)

The CI gate runs Haiku for fast, cheap pattern-matching on diffs. Not a multi-turn agent -- a quick triage pass. Gets Rem into the daily workflow and generates revenue at scale.

Cost: ~$0.04/scan. Priced at $0.10/scan.

```yaml
name: Rem Security Gate
on: [push]  # or pull_request, configurable via rem init
jobs:
  rem-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rezero/scan-action@v1
        with:
          fail-on: [critical, high]    # configurable threshold
        env:
          REM_API_KEY: ${{ secrets.REM_API_KEY }}
```

**Gate output when it finds something:**
```
Rem gate: 1 issue found

  CRITICAL  SQL injection in api/users.ts:47

  Gate scans check for common vulnerability patterns.
  Deep scans test auth bypasses, logic flaws, and
  multi-step attack chains. Last deep scan: never.

  Run: rem scan --deep
  Override: add `rem:accept` label
  Configure: .rem.yml

  Blocked (policy: fail on critical/high)
```

The "Last deep scan: never" line and the deep scan hint are intentional -- they drive conversion to paid on-demand scans without being pushy.

**Gate output with drift detection:**
```
Rem gate passed. No issues in this diff.

47% of your codebase has changed since your last
deep scan (34 days ago). Run: rem scan --deep
```

Drift detection tracks git stats since last deep scan. Resets after every deep scan. Factual nudge, not a nag.

### SARIF Output
- `rem scan . --format sarif --output results.sarif`
- Upload to GitHub Security tab -- findings appear inline on PRs
- Standard format = integrates with existing security tooling

### Security Badge
```markdown
[![Rem Security](https://rezero.sh/badge/org/repo)](https://rezero.sh/scan/org/repo)
```

Badge states:
- `scanned 12 days ago | 0 critical` (green)
- `scanned 89 days ago` (yellow)
- `last scan 147 days ago` (red/stale)
- `never scanned` (gray)

Social pressure. Developers care about README badges. A stale security badge is visible to everyone -- investors, users, collaborators. Drives recurring deep scans.

---

## Agent Capability Roadmap

### Priority 1: Easy Wins (build first)
1. **Dependency/CVE scanning** — Run `npm audit`, `pip audit`, `cargo audit`, `govulncheck` inside sandbox, feed structured results to agent. Agent validates which CVEs are actually reachable in the codebase.
2. **Incremental scanning** — Diff-based rescans. Don't re-analyze 1,200 files when 15 changed. Critical for CI/CD cost efficiency.
3. **Exploit generation** — When agent finds a vulnerability, it produces a working PoC (curl command, Python script). Findings with PoC exploits are 10x more convincing.

### Priority 2: High Impact (build next)
4. **In-sandbox code execution** — Detect stack (package.json → Node, requirements.txt → Python), install deps, run test suite. Agent can modify inputs to trigger failures = LLM-guided fuzzing.
5. **Multi-file reasoning with code graph** — tree-sitter AST analysis as an agent tool. Trace data flow: "show me all paths from HTTP request parameters to SQL queries."
6. **Scan memory** — Cross-run knowledge. v1.2.0 → v1.3.0 = focus on what changed. Extends to org-level configurable memory management.

### Priority 3: Differentiators (build for moat)
7. **Sandbox networking for web scans** — `docker compose up` the whole stack inside sandbox, scan locally. Test authenticated flows, local APIs, database injections in isolation.
8. **Custom scan profiles** — Template library ("fintech/PCI-DSS", "healthcare/HIPAA", "web3/smart-contract") + user-created profiles. Profile hub where community publishes configurations.
9. **Static analysis as internal tool** — Agent uses semgrep/bandit internally for recon, user never sees raw output. "Rem found 3 real vulnerabilities" (semgrep helped find them, but that's an implementation detail).
10. **Advanced DAST tools** — Give agent `nuclei`, `ffuf`, `sqlmap` as callable tools for web scans.

---

## Platform Quality & Feedback

### Scan Result Quality Scoring
- Track false positive rate (user marks finding as "not a bug")
- Severity accuracy (was the CRITICAL actually critical?)
- This becomes fine-tuning data for improving prompts
- Constant feedback loop: user feedback → better prompts → better scans

### Security of the Platform Itself
- Sandboxes can't phone home to user infrastructure
- Agent-generated exploit code runs in isolation
- Convex deploy keys in sandboxes scoped to that scan's data only
- Rate limiting on scan creation (prevent abuse)
- Regular self-scans (eat your own dogfood)

---

## Brand Strategy

### Current: Re:Zero / Rem
- **Strengths**: Memorable, great domain (rezero.sh), "return from zero" metaphor is perfect, strong aesthetic (midnight navy + rem blue, film grain, monospace)
- **Risk**: "Re:Zero" is trademarked by Kadokawa Corporation. "Rem" is a recognizable anime character.
- **Decision**: Keep the anime branding. The cybersec audience respects it — anime on a security tool's landing page signals authenticity. Corporate pages signal compliance-selling, not real security. Pentesters are the audience, and they're culturally aligned with this.
- **Risk mitigation**:
  - Commission original "Rem" character art (cyberpunk/hacker aesthetic, not blue-haired maid) — own the IP
  - "Rem" as a standalone word is not exclusively anime IP (sleep stage, font, band)
  - "Re:Zero" presented as "return from zero" concept
  - Keep the anime vibe, but gradually build *your own* version of Rem as a character
- **If C&D comes**: Swap anime-sourced art for original commissioned art. Keep the name, aesthetic, domain. $500 lawyer letter, weekend of updates. Not existential.
- **Operating entity**: Delaware C-Corp

### Two-Layer Brand Positioning
**The brand (site, Twitter, direct content):**
> "Autonomous security analysis. Rem finds vulnerabilities that matter."
- Technical, serious, for builders. Shows agent reasoning depth, scan traces, real findings.
- Landing page: terminal demo, agent capabilities, clean aesthetic.
- Speaks to people who respect craft. Never condescending.

**The ads (UGC, paid, viral content):**
> "You vibe coded it, now vibe check it."
- Catchy, memeable, for mass acquisition. Someone else's face.
- UGC campaigns, TikTok/Shorts, meme formats.
- Speaks to the mass market of new builders who need to be TOLD they have a security problem.

The brand says "we're serious." The ads say "you need this." Same product, different registers.
"Vibe code check" never appears on rezero.sh. It lives in the ad layer only.

### Open Source Strategy
- **CLI**: Open source (distribution mechanism, community contributions)
- **Profile/Agent Hub**: Community publishes scan configurations and agent profiles
- **Platform**: Proprietary (agent orchestration, scan history, team features, CI/CD)

---

## Build Priorities (ordered)

### Done
1. ~~**Real CLI** (`rem scan .`)~~ -- shipped
2. ~~**`rem init` + GitHub Action**~~ -- shipped
3. ~~**Autumn billing**~~ -- shipped
4. ~~**Prompt caching**~~ -- shipped
5. ~~**CI gate scan**~~ -- shipped (Haiku, synchronous, action.yml)

### Next Up
6. **Standard + Deep scan system** -- Sonnet for standard ($25), Opus for deep ($45). Dashboard shows "Standard Scan" / "Deep Scan" buttons instead of raw model picker. CLI: `rem scan .` (standard) / `rem scan --deep` (deep). Model selection is internal.
7. **CVE scanning** -- Run `npm audit`, `pip audit`, `cargo audit`, `govulncheck` inside Modal sandbox. Agent validates which CVEs are actually reachable.
8. **Dependency audit** -- Structured dependency analysis as agent tool. Feed results to orchestrator for triage.
9. **Code graph (tree-sitter)** -- AST-level agent tool. Trace data flows: "all paths from HTTP input to SQL queries." Multi-file reasoning.
10. **Scan memory** -- Cross-run knowledge. v1.2.0 → v1.3.0 = focus on what changed. Org-level configurable.
11. **Improve gate scan** -- Reduce false positives further, smart skip rules (docs-only changes, trivial diffs, debounce), incremental improvements to Haiku prompt.
12. **Agent harness architecture + planning** -- Rethink harness design. (Notes from Shresht — ask when we get here.)
13. **Codex SDK harness** -- OpenAI GPT-5.2 as second provider. ~20 min integration.
14. **OpenCode SDK improvement + testing** -- Improve GLM/OpenRouter harness, test reliability, SSE relay.
15. **Exploit generation** -- Agent produces working PoC (curl, Python script) for each finding. 10x more convincing.
16. **AgentMail integration** -- Test account creation via agentmail. Agent reads email for 2FA/verification codes during web scans.
17. **SARIF output** -- `rem scan . --format sarif`. GitHub Security tab integration.
18. **Profile hub** -- Community scan configurations. Prompt additions, skills, scope rules.
19. **Security badge** -- `rezero.sh/badge/org/repo` endpoint. SVG badge for READMEs. Drives recurring scans.

---

## Scan Depth Tiers

Users pick depth, not models. Model selection is internal.

- **CI Gate** (seconds, Haiku): Pattern matching on diffs. Not a multi-turn agent. Catches obvious issues, drives deep scan conversions. $0.10/scan.
- **Standard** (`rem scan`, ~15-30 min): Full repo or web app analysis, dependency audit. The default on-demand scan. $25/scan.
- **Deep** (`rem scan --deep`, ~30-60 min): Multi-pass analysis, more turns, broader exploration. For pre-launch, post-incident, quarterly audits. $45/scan.
- **Comprehensive** (future, ~1-2 hours): Everything above + code execution, fuzzing, exploit generation, multi-pass subagents, sandbox networking. $150/scan.

Depth tiers are about **thoroughness** (turns, tools, passes), not model quality. Standard uses Sonnet 4.6, Deep uses Opus. Users never see model names — they pick "Standard" or "Deep."

**Note**: Don't prematurely define tiers -- build tools, let the tiers emerge from capability.

---

## Scan Authorization & Legal

- **OSS repos (public)**: No authorization needed — it's public code
- **OSS repos (private)**: GitHub App OAuth — user explicitly grants access
- **Local repos**: User explicitly uploads — implicit consent
- **Web scans (own domain)**: Require domain verification (DNS TXT record or meta tag)
- **Web scans (others' domains)**: Passive analysis only (headers, public info, no active exploitation)
- **Terms of service**: Liability on the user for unauthorized scanning
- **Disclosure framework** (Project Zero model + CVE service):
  - Rem reports findings to the user. User has **30 days (critical) / 90 days (other)** to disclose or claim bug bounty.
  - 7 days only for actively exploited vulns (evidence of exploitation in the wild).
  - After timer, Re:Zero publishes advisory on **rezero.sh/advisories**: "A vulnerability exists in [library] [version]" — enough to warn, not enough to exploit. No exploit details, no PoC.
  - Advisory page doubles as marketing + SEO + credibility ("look at all the vulns Rem has found").
  - **CVE filing service** as a value-add: one-click "File CVE for VN-001" — auto-generates submission, user gets credited as discoverer.
  - **Opt-in responsible disclosure mode**: Rem auto-files GitHub Security Advisory (GHSA, private to maintainers). User can set timeline.
  - For high-severity findings post-timer: publish to oss-security mailing list.
  - Positions Re:Zero as responsible security org. Critical for Phase 2 credibility.
  - **Private vulnerability database**: All findings stored internally with full trace linkage. Used for prompt fine-tuning, vulnerability pattern analysis, and training data. Specific vuln metadata linked to traces = proprietary dataset (long-term moat).
- **Bug bounty integration** (internal only for now): Founder uses Rem to farm bounties as bootstrap revenue. Public integration TBD — allowing users to farm would flood platforms and kill founder's bounty income.

---

## Report Formats & Integrations

- **Web dashboard**: Real-time scan view (current)
- **SARIF**: GitHub Security tab integration
- **PDF reports**: For CTOs, board meetings, SOC 2 audits
- **JSON API**: Programmatic access to findings
- **Slack/Discord notifications**: "Rem found 3 new vulnerabilities in your latest push"
- **Webhook API**: Let users pipe findings into any system

---

## Competitive Landscape

### Hex Security (hex.co) — Primary Competitor
- **YC W26**, Seed stage, 3 founders (SF)
- Founders: Huzaifa Ahmad, Ahmad Khan (Waterloo Math), Prama Yudhistira (ex-Codegen [acquired], AMD)
- YC Partner: Gustaf Alstromer
- Positioning: "Agentic Offensive Security at Scale" — continuous AI pentesting
- Claims: Found vulns in dozens of YC companies, "$3B+ in prevented damages"
- **GTM: Enterprise/top-down** ("Book a discovery call")
- Tags: Reinforcement Learning, Cybersecurity

### Key Differentiators vs Hex
| | Re:Zero | Hex Security |
|---|---|---|
| **GTM** | Bottom-up PLG (CLI, self-serve) | Top-down enterprise (sales calls) |
| **ICP** | Indie devs, vibe coders, startups | Security teams, funded startups |
| **Entry point** | `rem scan .` (first scan free) | "Book a demo" |
| **Pricing** | Per-scan, transparent ($25-150) | Enterprise contracts |
| **Brand** | Anime/hacker culture | Professional/corporate |
| **Moat** | Open source CLI, community profiles, DX | YC network, enterprise relationships |

### Other Competitors
- **Snyk**: Code/dependency scanning, massive but not AI-agent-based
- **Semgrep**: Static analysis rules, no AI reasoning
- **GitHub Copilot Security**: If they build it, huge distribution advantage
- **Synack**: Human-powered pentest marketplace, expensive

### Defensibility
- Agent quality (fewer false positives, more real vulns)
- Tool ecosystem (profile hub, community configs = network effects)
- Developer experience (CLI + GH Action + self-serve ≠ enterprise sales)
- Speed to iterate (solo founder moves fast)
- Open source CLI (community trust, contributions, transparency)

---

## Data Strategy

### Retention & Privacy
- **Store everything, forever.** Soft delete only. Scan traces are training data gold.
- **No GDPR compliance.** Ban EU IPs, TOS prohibits scanning EU sites (liability on user).
- **Geographic scope**: North America + Asia. EU excluded.
- Users cannot fully delete data — TOS makes this clear upfront.

### Data as Asset
- Scan traces = fine-tuning data for improving agent quality
- Aggregate vulnerability patterns across repos = proprietary dataset
- Potential to sell anonymized trace data to model providers (e.g., Anthropic) for better security reasoning
- Quality feedback loop: user marks false positives → better prompts → better scans → training data

### Multi-Tenancy
- Convex queries scoped by userId (current architecture handles this)
- Each scan runs in isolated Modal sandbox — no cross-tenant data access by design

---

## The "rem init" Experience

Interactive, stack-aware setup. Transparent about costs. This is the single most important UX flow for adoption.

```
$ rem init

  Setting up Rem for your-app...

  Detected: Next.js 15, TypeScript, Convex, Clerk

  When should Rem check your code?
    > On merge to main (Recommended)
      On every PR [$0.10/PR with gate scan]
      Manual only (rem scan)

  What happens when vulnerabilities are found?
    > Block on critical/high (Recommended)
      Warn only (never block deploys)
      Block on all severities

  Monthly spending limit?
    > $50/month (Recommended for solo devs)
      $100/month
      No limit

  Based on your git history (~14 merges to main/month):
    Estimated CI cost: ~$0.56/month

  Created .rem.yml
  Created .github/workflows/rem.yml
  Created .remignore

  Run your first deep scan: rem scan
```

**New repo handling** (< 5 commits or new repo):
```
  This looks like a new project, so we can't measure from
  your history. For reference:
    20 merges/month = ~$0.80/month
    50 merges/month = ~$2.00/month
```

**When user selects "On every PR":**
```
  On every PR
  [Runs a gate scan ($0.10) on each PR.
   ~30 PRs/month = ~$3.00/month]
```

### .rem.yml Config

Dead simple. Readable in 5 seconds, editable in 10.

```yaml
ci:
  trigger: merge_to_main    # merge_to_main | every_pr | manual
  fail_on: [critical, high] # critical, high, medium, low

budget:
  monthly_limit: 50         # USD, null for no limit
```

No model selection in the config. That's our implementation detail.
In scan output we show "Scanned with Opus 4.6 | 47 turns | 12 findings" as metadata.

### Smart Skip Rules (built into CI gate)
- Skip if only docs/markdown changed
- Skip if diff is < N lines (trivial changes)
- Skip if last scan was < 1 hour ago (debounce)
- Configurable via `.remignore` patterns

These protect against bill shock without the user needing to configure anything.

---

## Agent Tools Catalog

### Currently Available
- `read_file` — read files from target repo
- `search_code` — grep patterns across codebase
- `submit_findings` — structured vulnerability report
- `ask_human` — human-in-the-loop questions
- Firecrawl MCP — web scraping, CVE lookup, documentation
- **Web-specific**: `navigate`, `get_page_content`, `click`, `fill_field`, `execute_js`, `screenshot`

### Priority Additions
- `npm_audit` / `pip_audit` / `cargo_audit` / `govulncheck` — dependency CVE scanning (structured JSON output fed to agent for reachability triage)
- `run_command` — execute arbitrary commands in sandbox (install deps, run tests, build project)
- `semgrep_scan` — run semgrep with auto config, feed results to agent as recon
- `tree_sitter_query` — AST-level code graph queries ("all paths from user input to SQL")
- `nuclei_scan` — run nuclei templates against web targets
- `generate_exploit` — agent writes + executes a PoC script in sandbox

### Future Additions
- `ffuf` — web fuzzing (directory/parameter discovery)
- `sqlmap` — automated SQL injection testing
- `docker_compose_up` — spin up entire app stack in sandbox
- `diff_scan` — compare two versions, focus on changed code
- `memory_recall` — query past scan results for this repo/org

---

## Profile Hub

### What's Configurable in a Profile

**1. Prompt Additions** (safe, just text)
- Pre-scan context: "This is a fintech app handling PCI data"
- Focus areas: "Prioritize authentication and payment flow security"
- Custom rules: "Always check for X" / "Treat any auth bypass as critical"
- Appended to the agent's system prompt before scan starts

**2. Skills** (safe, prompt + tool config bundles)
- A skill = prompt template + tool sequence configuration
- Example: "OWASP Top 10 Audit" — focused prompt + specific tool sequence
- Example: "Dependency Deep Dive" — runs all audit tools, traces CVE reachability
- Example: "Auth Flow Analysis" — focused on sessions, JWTs, OAuth
- Shareable on hub. Users can fork/modify. Based on Claude Agent skills pattern.

**3. Custom Tools** — DEFERRED
- Skipped for now. Skills provide enough customization without the security risk.
- Skills restrict what the agent focuses on, not what it can execute. Tool set is fixed by scan type.
- Custom tools (arbitrary code in sandbox) will be revisited once the platform is mature enough to do it properly.
- When revisited: network egress allowlist, resource limits, review process for hub publication.

**4. Scan Scope Rules**
- "Only scan src/" / "Skip tests/" / "Focus on files matching *.sol"
- File size limits, exclusion patterns
- Language/framework focus

**5. Environment Setup**
- "Install these deps before scanning"
- "Run docker compose up first"
- "Set these environment variables"

**6. Integration Hooks**
- "After scan, POST results to this webhook"
- "Send Slack notification on critical findings"
- "Upload SARIF to GitHub"

### Hub Model
- Public profiles: anyone can use
- Community-contributed: PR-based review process
- Private profiles: org-specific, not shared
- Fork/modify: clone a profile and customize it
- Versioned: profiles track changes over time
- **skills.sh integration**: Support Vercel's skills format natively (import from registry). Security-specific skills in Re:Zero's own `/skills` directory.

### Prompt Injection Security
Don't over-engineer. V1 mitigations:
1. **Classifier gate**: Run skill/prompt content through Haiku as safety check (~$0.001/check). "Does this attempt to override agent instructions, exfiltrate data, or call external services?" Catches obvious attacks.
2. **Report button**: Community moderation for the long tail. Users flag suspicious skills.
3. **Agent's own safety layer**: Opus has built-in instruction-following priorities. Not bulletproof (Pliny proves that), but a baseline.
4. **Private profiles**: User's own risk, their own sandbox. Liability not on us (same as app store).
- Note: Skills still grant access to code execution tools. The classifier gate is the main defense.
- Skip: network egress allowlisting, canary scanning, review process — overkill for v1.

---

## Launch Strategy

### Marketing Hook
**"Vibe Code Check"** — Position Rem as the natural complement to vibe coding.
- "You vibe coded it, now vibe check it."
- "POV: you shipped a Cursor project without running rem scan."
- The entire AI coding movement (Cursor, Bolt, Lovable, v0) needs a security step. That's Rem.

### Launch Week (everything at once, concentrated burst)

**Monday**: Twitter thread with scan video + "vibe code check" hook. Friends retweet.
**Tuesday**: Show HN ("Show HN: Re:Zero – Open source CLI for AI security scanning"). 10am ET. Be in comments all day.
**Wednesday**: Product Hunt. 5-10 people lined up for launch. Maker comment with TreeHacks story.
**Thursday**: Reddit blitz (r/netsec, r/programming, r/webdev, r/cybersecurity — different angle per sub).
**Friday**: Blog post live ("How I found 17 vulnerabilities in my own website using AI"). Security newsletter pitches sent.
**All week**: Group chat sharing (Gwern's 2k chat, SF ML communities), DMs to YouTubers, pull up to devtool events in SF.

### YouTuber Outreach (all free, cold DM with scan trace)
**Security-focused (most aligned):**
- John Hammond — cybersecurity, CTFs, tool reviews. Perfect fit.
- NetworkChuck — huge cybersec audience, loves flashy demos.
- LiveOverflow — technical security research, highly influential.
- HackerSploit — pentesting tutorials. Literally the ICP's viewing habits.
- David Bombal — networking/security, large audience.
- IppSec — CTF walkthroughs. Audience immediately gets it.

**Dev-focused:**
- Fireship — short-form, dev audience, loves novel tools.
- ThePrimeagen — would love the pentest + anime angle.
- Theo — covers new dev tools constantly (large reach).
- Web Dev Simplified, Traversy Media, CodeWithAntonio — audiences that ship fast and don't pentest.

Cold DM template: "We built an AI that does autonomous pentesting. It found 17 vulns in a live site in 21 minutes. Here's the trace. Want to try it on your own infra?"

Maximum impact in a single coordinated burst. Ride the wave of each platform amplifying the others.

**Ongoing — "We Scanned X" Series**
- Scan 3-5 popular open source projects per month
- Responsible disclosure first, then write up the results
- "We pointed Rem at [popular framework] and found N vulnerabilities in M minutes"
- Each one = tweet thread + blog post + HN submission
- CATNIP for the security and dev communities

### Distribution Channels

- **Twitter**: Primary. 1700 followers + high-profile retweet network. Post scan results, memes, "vibe code check" content.
- **Hacker News**: Show HN launch + ongoing "We Scanned X" posts.
- **Product Hunt**: One-time launch.
- **Reddit**: r/netsec, r/programming, r/webdev, r/cybersecurity. Different angle for each sub.
- **UGC Campaign**: Contact via existing relationship. "Developers react to AI finding vulnerabilities in their code." Target: 200M+ views via UGC farm.
- **Security Newsletters**: tl;dr sec, Daniel Miessler's Unsupervised Learning, This Week in Security. Pitch inclusion.
- **AI Coding Tool Communities**: Cursor Discord, Windsurf community, Bolt users. "Built with Cursor? Check with Rem."
- **Dev.to / Hashnode**: "How I found 17 vulnerabilities in my own website using AI" (the TreeHacks story).
- **YouTube**: Full scan recording videos, "How to secure your Next.js app in 5 minutes with Rem."
- **Private Group Chats**: Gwern's 2k-person chat, other SF ML/hacker communities.
- **GitHub Trending**: Open source CLI launch timed for Tue/Wed. Getting trending = permanent social proof.
- **Conference Lightning Talks**: SF meetups, security meetups, AI meetups. 5-min live demo.

### Content Types
1. **Scan result reveals** — "We scanned X and found Y" (highest engagement)
2. **Memes** — "vibe code check" format, security humor
3. **Live demo videos** — real-time scan with Rem spinner, findings popping up
4. **Comparison posts** — "Snyk vs Semgrep vs Rem on the same repo"
5. **Tutorial content** — "Secure your [framework] app in 5 minutes"
6. **Story posts** — "How a hackathon project found real vulnerabilities"

### Partnerships to Explore
- **AI coding tools** (Cursor, Bolt, v0) — co-marketing, "built with X, checked with Rem"
- **Hosting platforms** (Vercel, Railway, Fly) — security scanning as a feature recommendation
- **Model providers** (Anthropic) — case study for Claude in security applications

---

## Brand Backup Plan

If C&D forces a rename, best alternative: **Ronin**
- Masterless samurai = independent agent for hire
- Japanese aesthetic without specific IP
- "Deploy Ronin" / "Ronin found 3 vulnerabilities"
- ronin.sh domain
- Cyberpunk samurai mascot = 100% original IP
- The midnight/monospace aesthetic transfers perfectly
- Rated ~7.5/10 vs Re:Zero's 10/10

Other options: Revenant (returns from death), Nox (Latin for night), Vigil (keeping watch).

Current decision: Keep Re:Zero. Commission original Rem art. Deal with C&D if/when it comes.

---

## Open Questions

- [x] API credits for development -- $5K AWS credits → Bedrock. Same pricing, same SDK, drop-in replacement.
- [ ] Claude for Startups application -- unlocks after raising (requires VC backing). Nice-to-have, not blocking.
- [x] Exact per-scan pricing -- benchmarked with caching: Opus ~$16, Sonnet ~$9.50, Haiku gate ~$0.04
- [x] Pricing model -- usage-based per-scan. No subscription, no credits. Volume packs for power users.
- [ ] Benchmark Sonnet 4.6 quality on security tasks -- determines standard scan quality
- [ ] Implement prompt caching in agent harness -- 45% cost reduction, critical for margins
- [ ] Commission original Rem character art (cyberpunk hacker aesthetic)
- [ ] Team features timeline -- build after core product proves PMF
- [ ] Scan depth tiers -- let them emerge from tooling, don't prematurely define
- [ ] Bug bounty farming feasibility -- test Rem on HackerOne/Bugcrowd targets as bootstrap revenue
- [ ] UGC campaign planning -- get details from contact on replicating 200M-view campaigns
- [ ] Autumn integration scoping -- reach out via Mosaic connection, usage-based billing setup

---

## Key Contacts & Resources

- **Autumn** (payments): Warm intro via Mosaic (YC W25) founders. PMF confirmed -- T3 Chat adopted them Feb 2026. Usage-based billing in 3 functions.
- **Natural** (first enterprise prospect): CPO wants to run Rem against their product
- **Hex Security** (competitor): YC W26, seed stage, enterprise GTM, hex.co
- **Amazon Bedrock**: $5K AWS credits. Identical pricing to Anthropic API. Primary provider for dev phase.
- **Claude for Startups**: Requires VC backing. Unlocks post-raise ($25K credits). Not blocking.
- **OpenRouter**: Universal model access for OpenCode harness. Any model available there = available in Rem.

---

### Pricing References
- **Bessemer AI Pricing Playbook** (Feb 2026): bvp.com/atlas/the-ai-pricing-and-monetization-playbook -- AI agent companies see 50-60% gross margins, outcome/workflow-based pricing is the direction, hybrid models work for early stage.
- **Forbes/Metronome on Credits** (Oct 2025): Credits are transitional, not an end state. Most enterprise AI deals moving to usage-based or hybrid.
- **Anthropic Prompt Caching Docs**: Cache read = 10% base input. Cache write = 125% base input. 5-min default TTL, 1-hour available. Stacks with batch API.

*Last updated: Feb 17, 2026*
