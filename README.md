# Re:Zero

## Reverse Engineer Anything.

The universal autonomous red teaming platform. Point it at any attack surface — source code, web infrastructure, physical hardware — and AI agents will reverse engineer it, find vulnerabilities, and generate a full security audit. One platform, any target, zero prior knowledge required.

## The Pitch

There are ~500k unfilled cybersecurity jobs globally. Pen testers cost $200-400/hr. Most companies test annually if at all. Hardware supply chain audits require specialists that barely exist.

Every existing player is vertical-locked: Pentera does networks, Synack (YC W13) does web apps, Snyk does code. Nobody does hardware. But the reasoning pattern is the same across all surfaces:

1. **Recon** — map the attack surface
2. **Hypothesize** — what could be vulnerable?
3. **Probe** — test the hypothesis
4. **Escalate** — how far can you go?
5. **Report** — document findings + remediation

The only thing that changes is the tool suite. That's Re:Zero.

## Stuff we need to do

- [ ] Get Claude Code SDK on reverse engineering
- [ ] Fine-tune GLM-4.7V and Nemotron 3 Nano (30b-A3B) on reverse engineering and pentesting
- [ ] Set up a web app (dashboard, "projects", project types so web, codebase, and hardware, with overlap allowed)
- [ ] Convex backend (including functions which connect to modal and monitor your relevant sandboxes)
- [ ] Modal sandboxes
- [ ] Agent harness: skills, ghidra/other mcps, subagents -> opencode?
- [ ] Targets for demo: open source repos (target C/C++, IoT, MCPs, OpenClaw), drone, 3d printer, laptop
- [ ] FPGA logic analyzer firmware as a tool for the agent

## The Four Modes
1. Code mode (OSS)
2. Hardware RE (drone)
3. Side-channel mode (extract AES key from power traces via FPGA)
4. Web

## Team
1. Shresht: claude code sdk, agent harnesses, modal sandboxes, convex backend, frontend (live agent streams, camera feed views, waveform visualization for fpga travces, scan results, unified reports), 0-day farming pipeline (on sandboxes), perplexity sonar, demo
2. Kenneth: ChipWhisperer HDL -> Genesys 2, Pmod ADC, trigger logic, DDR3 trace buffer, python api for agent integration, ESP32 AES target setup with shunt resistor
3. Mouad: find training data, QLoRAs (cybersec reasoning, vulnerability reasoning traces, PCBs, protocol analysis) on GLM-4.7V, Nemotron 3 Nano, create vLLM config for Modal deployment
4. William: ESP32 probe controller firmware (drone, etc), drone flight controller interface, probe jig, wiring, camera, help shresht with frontend and agent harnesses, join kenneth on fpga 

## Project Structure

```
re-zero/
├── web/           # Next.js dashboard, Convex, Clerk auth
├── server/        # FastAPI, Claude Code SDK agents, Modal sandboxes, Perplexity Sonar
├── hardware/      # ESP32 firmware (William), FPGA RTL + Python API (Kenneth)
├── training/      # data gen, QLoRA scripts, vLLM deploy configs (Mouad)
└── targets/       # demo target info, intentionally vulnerable test apps
```

### Stack
- **Frontend:** Next.js, shadcn/ui, Vercel AI SDK UI, Clerk, Vercel
- **Database:** Convex (real-time sync for live agent state → dashboard)
- **API + Agents:** FastAPI, Claude Code SDK, Anthropic Agent SDK, Pydantic
- **Compute:** Modal (sandboxes for code targets, GPUs for model serving + training)
- **Fine-tuned Models:** GLM-4.7, Nemotron 3 Nano — both QLoRA, served via vLLM on Modal
- **Research:** Perplexity Sonar API (CVE lookup, datasheets, component ID)
- **Hardware Probing:** ESP32 (PlatformIO), USB serial bridge
- **Side-Channel:** Kintex-7 FPGA (Verilog), ChipWhisperer Python analyzer
- **Deployment:** Vercel (frontend), Railway (API server), Modal (sandboxes + gpus)

## Target customers
- Any app/website/software big enough to need security for its users
- IoT companies
- Data centers
- Cloud providers
- Defense/government
- Automotive 
- Medical devices
- Power grids, water treatment, manufacturing
- Semiconductor companies (chip-level security)
- Crypto
- Anyone who needs to get compliance certified

## Tracks we're targeting
- Anthropic Claude Code SDK
- Modal (sandboxes and main track)
- Nvidia (inference and open models track)
- Human Capital (company track)
- YC track (Salt Security)
- Human Capital Fellowship track
- Greylock (multiturn agent track)
- Vercel (best use of vercel)
- Perplexity (Sonar API track)