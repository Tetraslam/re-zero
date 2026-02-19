"""Sandbox orchestrator — spins up Modal sandboxes for scan jobs.

Sandboxes write directly to Convex (not back to the server) since
Modal containers can't reach localhost.
"""

import modal
import os

MINUTES = 60

# ── Tier configuration (source of truth) ─────────────────────────────
TIER_CONFIG = {
    "maid": {
        "label": "Maid",
        "autumn_feature": "standard_scan",
        "default_model": "claude-sonnet-4.6",
        "models": {
            "claude-sonnet-4.6": {"label": "Sonnet 4.6", "harness": "claude", "api_id": "claude-sonnet-4-5-20250929"},
            "glm-5": {"label": "GLM-5", "harness": "opencode", "provider": "openrouter", "model_id": "z-ai/glm-5"},
        },
    },
    "oni": {
        "label": "Oni",
        "autumn_feature": "deep_scan",
        "default_model": "claude-opus-4.6",
        "models": {
            "claude-opus-4.6": {"label": "Opus 4.6", "harness": "claude", "api_id": "claude-opus-4-6"},
            "kimi-k2.5": {"label": "Kimi K2.5", "harness": "opencode", "provider": "openrouter", "model_id": "moonshotai/kimi-k2.5"},
        },
    },
}


def validate_tier_model(tier: str, model: str | None) -> tuple[str, str, str]:
    """Validate tier/model combo. Returns (tier, resolved_model, harness)."""
    if tier not in TIER_CONFIG:
        raise ValueError(f"Unknown tier: {tier}")
    cfg = TIER_CONFIG[tier]
    resolved = model or cfg["default_model"]
    if resolved not in cfg["models"]:
        raise ValueError(f"Model {resolved} not available in tier {tier}")
    return tier, resolved, cfg["models"][resolved]["harness"]


def _get_anthropic_client():
    """Create Anthropic client — uses Bedrock if USE_BEDROCK=true, else direct API."""
    if os.environ.get("USE_BEDROCK") == "true":
        from anthropic import AnthropicBedrock
        return AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
    from anthropic import Anthropic
    return Anthropic()


def _get_model_id(model_name: str) -> str:
    """Resolve our model name to the actual API model ID.

    Non-Bedrock: returns the api_id from TIER_CONFIG (e.g. claude-opus-4-6).
    Bedrock: returns the Bedrock-specific model ARN.
    """
    # Look up api_id from TIER_CONFIG
    api_id = model_name
    for tier_cfg in TIER_CONFIG.values():
        if model_name in tier_cfg["models"]:
            api_id = tier_cfg["models"][model_name].get("api_id", model_name)
            break

    if os.environ.get("USE_BEDROCK") != "true":
        return api_id
    bedrock_mapping = {
        "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
        "claude-sonnet-4-5-20250929": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "claude-haiku-4-5-20251001": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
    return bedrock_mapping.get(api_id, api_id)


def _use_bedrock() -> bool:
    """Check if we're using Bedrock."""
    return os.environ.get("USE_BEDROCK") == "true"

# MCP servers available to the agent
MCP_SERVERS = [
    {
        "type": "url",
        "url": "https://mcp.firecrawl.dev/fc-a82ab47650734b138291950300675c4a/v2/mcp",
        "name": "firecrawl",
    },
]

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "jq")
    .pip_install(
        "httpx",
        "anthropic[bedrock]",
        "pydantic",
    )
)

web_sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .pip_install(
        "httpx",
        "anthropic[bedrock]",
        "pydantic",
        "playwright",
        "stagehand",
    )
    .run_commands(
        "playwright install --with-deps chromium",
        # Symlink Playwright's Chromium to a fixed path for Stagehand's SEA binary.
        # Playwright installs to versioned dirs — this makes the path stable.
        'bash -c \'CHROME=$(find /root/.cache/ms-playwright -type f \\( -name chrome -o -name headless_shell \\) -executable 2>/dev/null | head -1) && '
        'if [ -z "$CHROME" ]; then echo "FATAL: No Chromium binary found after playwright install" && exit 1; fi && '
        'ln -sf "$CHROME" /usr/local/bin/stagehand-chrome && '
        'echo "Linked $CHROME -> /usr/local/bin/stagehand-chrome"\'',
    )
    .env({"CHROME_PATH": "/usr/local/bin/stagehand-chrome"})
)

# OpenCode images — for OpenRouter models (GLM-5, Kimi K2.5, etc.)
opencode_sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "jq", "unzip")
    .pip_install("httpx", "pydantic", "anthropic[bedrock]")
    .run_commands(
        # Install OpenCode CLI
        "curl -fsSL https://opencode.ai/install | bash",
        # Install Bun (for custom TypeScript tools)
        "curl -fsSL https://bun.sh/install | bash",
    )
    .env({"PATH": "/root/.opencode/bin:/root/.bun/bin:/root/.local/bin:/usr/local/bin:/usr/bin:/bin"})
)

opencode_web_sandbox_image = (
    opencode_sandbox_image
    .pip_install("playwright", "aiohttp", "stagehand")
    .run_commands(
        "playwright install --with-deps chromium",
        'bash -c \'CHROME=$(find /root/.cache/ms-playwright -type f \\( -name chrome -o -name headless_shell \\) -executable 2>/dev/null | head -1) && '
        'if [ -z "$CHROME" ]; then echo "FATAL: No Chromium binary found after playwright install" && exit 1; fi && '
        'ln -sf "$CHROME" /usr/local/bin/stagehand-chrome && '
        'echo "Linked $CHROME -> /usr/local/bin/stagehand-chrome"\'',
    )
    .env({"CHROME_PATH": "/usr/local/bin/stagehand-chrome"})
)

app = modal.App("re-zero-sandbox")


@app.function(
    image=sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_oss_scan(
    scan_id: str,
    project_id: str,
    repo_url: str,
    model: str = "claude-opus-4.6",
    convex_url: str = "",
    convex_deploy_key: str = "",
    storage_id: str = "",
):
    """Run an OSS security scan in a Modal sandbox."""
    import subprocess
    import os

    work_dir = "/root/target"

    if storage_id:
        # Tarball upload flow — download from Convex storage and extract
        await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Rem is downloading the uploaded code...")
        url = await _get_storage_url(convex_url, convex_deploy_key, storage_id)
        subprocess.run(["curl", "-sL", "-o", "/tmp/repo.tar.gz", url], check=True, capture_output=True)
        os.makedirs(work_dir, exist_ok=True)
        subprocess.run(["tar", "xzf", "/tmp/repo.tar.gz", "-C", work_dir], check=True, capture_output=True)
    else:
        # Git clone flow
        await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Rem is cloning the repository...")
        subprocess.run(
            ["git", "clone", "--depth=1", repo_url, work_dir],
            check=True,
            capture_output=True,
        )

    result = subprocess.run(
        ["find", work_dir, "-type", "f", "-not", "-path", "*/.git/*"],
        capture_output=True,
        text=True,
    )
    file_list = result.stdout.strip().split("\n")[:200]

    source_label = repo_url if repo_url else "uploaded tarball"
    await _push_action(
        convex_url, convex_deploy_key, scan_id, "observation",
        f"Rem loaded {source_label} — {len(file_list)} files indexed"
    )

    await _run_claude_agent(
        scan_id, project_id, repo_url, work_dir, file_list,
        convex_url, convex_deploy_key, model=model,
    )


async def _convex_mutation(convex_url: str, deploy_key: str, path: str, args: dict):
    """Call a Convex mutation directly from the sandbox."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/mutation",
            json={"path": path, "args": args},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def _push_action(convex_url: str, deploy_key: str, scan_id: str, action_type: str, payload):
    """Push an action directly to Convex."""
    await _convex_mutation(convex_url, deploy_key, "actions:push", {
        "scanId": scan_id,
        "type": action_type,
        "payload": payload,
    })


async def _convex_query(convex_url: str, deploy_key: str, path: str, args: dict):
    """Call a Convex query directly from the sandbox."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/query",
            json={"path": path, "args": args},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def _get_storage_url(convex_url: str, deploy_key: str, storage_id: str) -> str:
    """Get a download URL for a file in Convex storage."""
    result = await _convex_query(convex_url, deploy_key, "storage:getUrl", {
        "storageId": storage_id,
    })
    url = result.get("value", result) if isinstance(result, dict) else result
    if not url:
        raise ValueError(f"Failed to get storage URL for {storage_id}")
    return url


async def _ask_human(
    convex_url: str, deploy_key: str,
    scan_id: str, question: str,
) -> str:
    """Ask the human operator a question and wait for their response.

    Creates a prompt in Convex, pushes a human_input_request action to the
    trace, then polls until the user responds (or 10 minutes elapse).
    """
    import asyncio

    # Create the prompt record
    result = await _convex_mutation(convex_url, deploy_key, "prompts:create", {
        "scanId": scan_id,
        "question": question,
    })
    prompt_id = result["value"]

    # Push a trace action so the frontend shows the input UI
    await _push_action(convex_url, deploy_key, scan_id, "human_input_request", {
        "promptId": prompt_id,
        "question": question,
    })

    # Poll until answered (10 min timeout, 3s interval)
    for _ in range(200):
        await asyncio.sleep(3)
        resp = await _convex_query(convex_url, deploy_key, "prompts:get", {
            "promptId": prompt_id,
        })
        prompt = resp.get("value") or resp
        if isinstance(prompt, dict) and prompt.get("status") == "answered":
            return prompt.get("response", "")

    return "(no response — operator timed out)"


async def _upload_screenshot(convex_url: str, deploy_key: str, screenshot_bytes: bytes) -> str:
    """Upload screenshot to Convex file storage, return storageId."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{convex_url}/api/mutation",
            json={"path": "storage:generateUploadUrl", "args": {}},
            headers={"Authorization": f"Convex {deploy_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        upload_url = resp.json()["value"]

        resp = await client.post(
            upload_url,
            content=screenshot_bytes,
            headers={"Content-Type": "image/png"},
            timeout=30,
        )
        resp.raise_for_status()
        # Upload returns either {"storageId":"..."} or a bare "..." string
        import json
        try:
            data = json.loads(resp.text)
            if isinstance(data, dict) and "storageId" in data:
                return data["storageId"]
            return str(data)
        except (json.JSONDecodeError, TypeError):
            return resp.text.strip().strip('"')


def _extract_snippet(work_dir: str, location: str) -> str | None:
    """Parse a location like 'src/auth.py:31-36' and read those lines from the repo."""
    import os
    import re

    m = re.match(r"^(.+?):(\d+)(?:-(\d+))?", location)
    if not m:
        return None
    file_path, start_str, end_str = m.group(1), m.group(2), m.group(3)
    start = int(start_str)
    end = int(end_str) if end_str else start

    abs_path = os.path.join(work_dir, file_path)
    try:
        with open(abs_path) as f:
            lines = f.readlines()
        snippet_lines = lines[start - 1 : end]
        if not snippet_lines:
            return None
        return "".join(snippet_lines)
    except Exception:
        return None


async def _compile_report(
    convex_url: str, deploy_key: str,
    scan_id: str, project_id: str,
    work_dir: str = "",
):
    """Second-pass agent that reads the scan trace and produces a structured report.

    Called when the scanning agent finishes without a proper report. A fresh
    context means it can focus entirely on structuring findings.
    """
    import anthropic
    import json

    # Fetch all actions from the trace
    resp = await _convex_query(convex_url, deploy_key, "actions:listByScan", {
        "scanId": scan_id,
    })
    actions = resp.get("value", resp) if isinstance(resp, dict) else resp

    # Build a condensed trace for the report agent — reasoning + observations + tool summaries
    trace_lines = []
    for action in (actions if isinstance(actions, list) else []):
        a_type = action.get("type", "")
        payload = action.get("payload", "")
        if a_type == "reasoning":
            trace_lines.append(f"[reasoning] {payload}")
        elif a_type == "observation":
            trace_lines.append(f"[observation] {payload}")
        elif a_type == "tool_call" and isinstance(payload, dict):
            trace_lines.append(f"[tool_call] {payload.get('summary', '')}")
        elif a_type == "tool_result" and isinstance(payload, dict):
            summary = payload.get("summary", "")
            content = payload.get("content", "")
            # Include content for results that have security-relevant data
            if content and len(str(content)) < 2000:
                trace_lines.append(f"[tool_result] {summary}\n  {str(content)[:1500]}")
            else:
                trace_lines.append(f"[tool_result] {summary}")

    trace_text = "\n".join(trace_lines)
    # Cap at ~80k chars to stay within context
    if len(trace_text) > 80000:
        trace_text = trace_text[:80000] + "\n... (trace truncated)"

    client = _get_anthropic_client()

    system = """You are a security report writer. You're given the full trace from an automated penetration test / security scan. Your job is to read through the trace and produce a structured vulnerability report.

Extract every distinct vulnerability or security issue mentioned in the trace. For each one, create a separate finding with:
- title: specific name of the vulnerability
- severity: critical/high/medium/low/info
- description: what the vulnerability is and why it matters
- location: URL, file path, or page where it was found
- recommendation: how to fix it
- code_snippet: the actual evidence — HTTP headers, HTML, JS code, response content, etc. that demonstrates the issue

Be thorough — if the scanning agent mentioned it, include it. Don't combine multiple issues into one finding. The summary should be 2-3 sentences covering the overall security posture."""

    response = client.messages.create(
        model=_get_model_id("claude-opus-4.6"),
        max_tokens=8192,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[{
            "name": "submit_findings",
            "description": "Submit the structured security report",
            "cache_control": {"type": "ephemeral"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        }],
        messages=[{"role": "user", "content": f"Here is the full trace from a security scan. Read through it and produce a structured vulnerability report using the submit_findings tool.\n\n{trace_text}"}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_findings":
            findings = block.input.get("findings", [])
            summary = block.input.get("summary", "Report compiled from scan trace.")
            await _push_action(convex_url, deploy_key, scan_id, "observation",
                f"Report writer compiled {len(findings)} findings from trace")
            await _submit_report(
                convex_url, deploy_key,
                scan_id, project_id,
                findings, summary,
                work_dir=work_dir,
            )
            return

    # Report agent also failed — mark scan failed
    await _convex_mutation(convex_url, deploy_key, "scans:updateStatus", {
        "scanId": scan_id,
        "status": "failed",
        "error": "Could not compile a structured report from the scan trace.",
    })


async def _submit_report(
    convex_url: str, deploy_key: str,
    scan_id: str, project_id: str, findings: list, summary: str,
    work_dir: str = "",
):
    """Submit report and mark scan completed directly in Convex.

    Assigns each finding a sequential ID (VN-001, VN-002, ...) before saving.
    Extracts code snippets from the repo when the LLM didn't include them.
    """
    for i, finding in enumerate(findings):
        finding["id"] = f"VN-{i + 1:03d}"
        # Map snake_case from LLM to camelCase for Convex
        if "code_snippet" in finding:
            finding["codeSnippet"] = finding.pop("code_snippet")
        # Fallback: extract from repo if LLM didn't include a snippet
        if not finding.get("codeSnippet") and finding.get("location") and work_dir:
            snippet = _extract_snippet(work_dir, finding["location"])
            if snippet:
                finding["codeSnippet"] = snippet

    await _convex_mutation(convex_url, deploy_key, "reports:submit", {
        "scanId": scan_id,
        "projectId": project_id,
        "findings": findings,
        "summary": summary,
    })
    await _convex_mutation(convex_url, deploy_key, "scans:updateStatus", {
        "scanId": scan_id,
        "status": "completed",
    })


async def _run_claude_agent(
    scan_id: str,
    project_id: str,
    repo_url: str,
    work_dir: str,
    file_list: list[str],
    convex_url: str,
    deploy_key: str,
    model: str = "claude-opus-4.6",
):
    """Run security scan using Claude API with the specified model."""
    import anthropic
    import os
    import subprocess

    client = _get_anthropic_client()

    system_prompt = f"""You are Rem, a security researcher performing a vulnerability audit on a codebase.

Repository: {repo_url}
Working directory: {work_dir}

Your task:
1. Analyze the codebase for security vulnerabilities
2. Focus on: injection flaws, authentication issues, data exposure, misconfigurations, dependency vulnerabilities
3. For each finding, provide: title, severity (critical/high/medium/low/info), description, file location, remediation
4. IMPORTANT: For each finding, include a code_snippet field with the exact vulnerable code lines you found. Copy the relevant lines verbatim from the files you read. Include just the vulnerable section (typically 3-15 lines), not entire files.

You have Firecrawl tools for web scraping and search. Use firecrawl_search to look up known CVEs for dependencies you find, or firecrawl_scrape to check project documentation and websites for security-relevant info.

Be thorough but precise. Only report real vulnerabilities, not style issues.

Files in repository:
{chr(10).join(file_list[:100])}
"""

    await _push_action(convex_url, deploy_key, scan_id, "reasoning", "Rem starting security analysis...")

    messages = [{"role": "user", "content": "Analyze this codebase for security vulnerabilities. Read key files, identify attack surfaces, and produce a structured security report."}]

    tools = [
        {
            "name": "read_file",
            "description": "Read a file from the repository",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repo root"}
                },
                "required": ["path"],
            },
        },
        {
            "name": "search_code",
            "description": "Search for a pattern in the codebase",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Grep pattern to search for"}
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "submit_findings",
            "description": "Submit the final security report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string", "description": "File path and line numbers, e.g. src/auth.py:31-36"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string", "description": "The exact vulnerable code lines copied from the file"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        },
        {
            "name": "ask_human",
            "description": "Ask the human operator a question and wait for their response. Use this when you need information only a human can provide: 2FA codes, CAPTCHAs, login instructions, clarification about the target, or any situation where you're stuck and need human guidance.",
            "cache_control": {"type": "ephemeral"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the operator. Be specific about what you need and why."},
                },
                "required": ["question"],
            },
        },
    ]

    # Convert system prompt to content block format for prompt caching.
    # System prompt + tools are static across all turns — cached after turn 1,
    # read from cache on turns 2-N at 10% of input cost.
    system_cached = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    mcp_tools = [{"type": "mcp_toolset", "mcp_server_name": s["name"]} for s in MCP_SERVERS]

    turn = 0
    while True:
        turn += 1

        # MCP servers can have transient failures — retry, then fall back without them.
        # Bedrock doesn't support MCP beta API, so use standard messages.create() directly.
        response = None
        if _use_bedrock():
            response = client.messages.create(
                model=_get_model_id(model),
                max_tokens=4096,
                system=system_cached,
                tools=tools,
                messages=messages,
            )
        else:
            for attempt in range(3):
                try:
                    response = client.beta.messages.create(
                        model=model,
                        max_tokens=4096,
                        system=system_cached,
                        tools=[*tools, *mcp_tools] if attempt < 2 else tools,
                        mcp_servers=MCP_SERVERS if attempt < 2 else [],
                        messages=messages,
                        betas=["mcp-client-2025-11-20"],
                    )
                    break
                except Exception as e:
                    if attempt < 2 and "MCP" in str(e):
                        import asyncio
                        await asyncio.sleep(2)
                        continue
                    raise

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Push text/reasoning blocks
        text_blocks = [b.text for b in assistant_content if hasattr(b, "text") and b.type == "text"]
        for text in text_blocks:
            if text.strip():
                await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

        # Push MCP tool calls/results to trace (already executed server-side)
        # Build tool_use_id -> tool name map for pairing results with calls
        mcp_tool_names = {}
        for block in assistant_content:
            if block.type == "mcp_tool_use":
                mcp_tool_names[block.id] = block.name

        for block in assistant_content:
            if block.type == "mcp_tool_use":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": block.name,
                    "summary": f"{block.name}({', '.join(f'{k}={repr(v)[:60]}' for k, v in (block.input or {}).items())})"[:120],
                    "input": block.input,
                })
            elif block.type == "mcp_tool_result":
                tool_name = mcp_tool_names.get(block.tool_use_id, "mcp")
                # Extract text from MCP content blocks
                content_text = ""
                if hasattr(block, "content") and block.content:
                    if isinstance(block.content, str):
                        content_text = block.content
                    elif isinstance(block.content, list):
                        parts = []
                        for item in block.content:
                            if hasattr(item, "text"):
                                parts.append(item.text)
                            else:
                                parts.append(str(item))
                        content_text = "\n".join(parts)
                    else:
                        content_text = str(block.content)
                # Cap at 50KB for Convex doc size limits
                content_text = content_text[:50000]
                char_count = f"{len(content_text):,}" if content_text else "0"
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": tool_name,
                    "summary": f"{tool_name} returned {char_count} chars",
                    "content": content_text,
                })

        # Only process LOCAL tool_use blocks (MCP tools are handled server-side)
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses and response.stop_reason == "end_turn":
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "ask_human":
                question = tool_use.input["question"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "ask_human",
                    "summary": f"Asking operator: {question[:80]}",
                    "input": {"question": question},
                })
                human_response = await _ask_human(
                    convex_url, deploy_key, scan_id, question,
                )
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "ask_human",
                    "summary": f"Operator responded",
                    "content": human_response,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Operator response: {human_response}",
                })

            elif tool_use.name == "read_file":
                file_path = tool_use.input["path"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "read_file",
                    "summary": f"Reading {file_path}",
                    "input": {"path": file_path},
                })

                abs_path = os.path.join(work_dir, file_path)
                try:
                    with open(abs_path) as f:
                        content = f.read(50000)
                    result_text = content
                except Exception as e:
                    result_text = f"Error reading file: {e}"

                lines = result_text.count("\n") + 1
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "read_file",
                    "summary": f"Read {file_path} ({len(result_text):,} chars, {lines} lines)",
                    "path": file_path,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "search_code":
                pattern = tool_use.input["pattern"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "search_code",
                    "summary": f"Searching for `{pattern}`",
                    "input": {"pattern": pattern},
                })

                try:
                    grep_result = subprocess.run(
                        ["grep", "-rn", pattern, work_dir,
                         "--include=*.py", "--include=*.js", "--include=*.ts",
                         "--include=*.go", "--include=*.c", "--include=*.cpp",
                         "--include=*.java", "--include=*.rs", "--include=*.rb",
                         "--include=*.php", "--include=*.sol", "--include=*.yaml",
                         "--include=*.yml", "--include=*.json", "--include=*.toml",
                         "--include=*.cfg", "--include=*.ini", "--include=*.env",
                         "--include=*.sh", "--include=*.bash", "--include=*.dockerfile",
                         "--include=Makefile", "--include=*.html", "--include=*.xml"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    output = grep_result.stdout[:10000]
                except Exception as e:
                    output = f"Error: {e}"

                match_count = output.count("\n") if output.strip() else 0
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "search_code",
                    "summary": f"Found {match_count} matches for `{pattern}`",
                    "pattern": pattern,
                    "matches": match_count,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": output if output else "No matches found.",
                })

            elif tool_use.name == "submit_findings":
                findings = tool_use.input.get("findings", [])
                summary = tool_use.input.get("summary", "")
                n = len(findings)

                # If the agent crammed everything into the summary with few/no
                # structured findings, hand off to the report writer instead.
                if n <= 1 and len(summary) > 300:
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        "Findings are under-structured — handing off to report writer for proper breakdown...")
                    await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)
                    return

                await _push_action(convex_url, deploy_key, scan_id, "observation", f"Rem is compiling report — {n} findings identified")
                await _submit_report(
                    convex_url, deploy_key,
                    scan_id, project_id,
                    findings,
                    summary,
                    work_dir=work_dir,
                )
                return

        messages.append({"role": "user", "content": tool_results})

    # Agent stopped without calling submit_findings — hand off to report writer
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Scanning complete. Handing off to report writer...")
    await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)


# ---------------------------------------------------------------------------
# OpenCode agent helpers
# ---------------------------------------------------------------------------

def _get_opencode_model_label(model: str) -> str:
    """Get display label for an OpenCode model from TIER_CONFIG."""
    for tier_cfg in TIER_CONFIG.values():
        if model in tier_cfg["models"]:
            return tier_cfg["models"][model]["label"]
    return model


def _build_opencode_config(model: str) -> dict:
    """Build opencode.json config for the given model via OpenRouter.

    Uses :nitro suffix for throughput-based provider sorting.
    See: https://openrouter.ai/docs/guides/routing/provider-selection#provider-sorting
    """
    # Look up model_id from TIER_CONFIG
    model_id = None
    for tier_cfg in TIER_CONFIG.values():
        if model in tier_cfg["models"]:
            model_id = tier_cfg["models"][model].get("model_id", model)
            break
    if not model_id:
        raise ValueError(f"Unknown OpenCode model: {model}")

    label = _get_opencode_model_label(model)
    # :nitro suffix = sort by throughput on OpenRouter
    nitro_id = f"{model_id}:nitro"

    # Use custom @ai-sdk/openai-compatible provider instead of built-in
    # openrouter provider. This lets us set includeUsage:true to fix
    # NaN token counts (OpenCode #423 / ai-sdk #6774). The built-in
    # openrouter provider has a strict schema that rejects includeUsage.
    provider_id = "openrouter-rem"
    return {
        "provider": {
            provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "OpenRouter",
                "options": {
                    "baseURL": "https://openrouter.ai/api/v1",
                    "apiKey": "{env:OPENROUTER_API_KEY}",
                    "includeUsage": True,
                },
                "models": {
                    nitro_id: {
                        "name": label,
                        "limit": {
                            "context": 131072,
                            "output": 8192,
                        },
                    },
                },
            },
        },
        "model": f"{provider_id}/{nitro_id}",
    }


# Custom tool: submit_findings
_TOOL_SUBMIT_FINDINGS = '''
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Submit the final security report with a summary and array of findings. Each finding should have: title, severity (critical/high/medium/low/info), description, location (file path or URL), recommendation, and code_snippet (the actual vulnerable code lines).",
  args: {
    summary: tool.schema.string().describe("Brief 2-3 sentence overview of the security posture"),
    findings: tool.schema.array(tool.schema.object({
      title: tool.schema.string().describe("Specific name of the vulnerability"),
      severity: tool.schema.enum(["critical", "high", "medium", "low", "info"]).describe("Severity level"),
      description: tool.schema.string().describe("What the vulnerability is and why it matters"),
      location: tool.schema.string().optional().describe("File path and line numbers, e.g. src/auth.py:31-36"),
      recommendation: tool.schema.string().optional().describe("How to fix the vulnerability"),
      code_snippet: tool.schema.string().optional().describe("The exact vulnerable code lines copied from the file"),
    })).describe("Array of vulnerability findings"),
  },
  async execute(args) {
    const convexUrl = process.env.CONVEX_URL;
    const deployKey = process.env.CONVEX_DEPLOY_KEY;
    const scanId = process.env.SCAN_ID;
    const projectId = process.env.PROJECT_ID;

    if (!convexUrl || !deployKey || !scanId || !projectId) {
      return "Error: Missing environment variables for Convex connection.";
    }

    const findings = args.findings.map((f, i) => ({
      id: `VN-${String(i + 1).padStart(3, "0")}`,
      title: f.title,
      severity: f.severity,
      description: f.description,
      location: f.location,
      recommendation: f.recommendation,
      codeSnippet: f.code_snippet,
    }));

    // Submit report to Convex
    await fetch(`${convexUrl}/api/mutation`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Convex ${deployKey}` },
      body: JSON.stringify({ path: "reports:submit", args: { scanId, projectId, findings, summary: args.summary } }),
    });

    // Mark scan as completed
    await fetch(`${convexUrl}/api/mutation`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Convex ${deployKey}` },
      body: JSON.stringify({ path: "scans:updateStatus", args: { scanId, status: "completed" } }),
    });

    return `Report submitted with ${findings.length} findings.`;
  },
})
'''

# Custom tool: ask_human
_TOOL_ASK_HUMAN = '''
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Ask the human operator a question and wait for their response. Use this when you need information only a human can provide: 2FA codes, CAPTCHAs, login instructions, clarification about the target, or any situation where you're stuck.",
  args: {
    question: tool.schema.string().describe("The question to ask the operator. Be specific about what you need and why."),
  },
  async execute(args) {
    const convexUrl = process.env.CONVEX_URL;
    const deployKey = process.env.CONVEX_DEPLOY_KEY;
    const scanId = process.env.SCAN_ID;

    if (!convexUrl || !deployKey || !scanId) {
      return "Error: Missing environment variables.";
    }

    const headers = { "Content-Type": "application/json", "Authorization": `Convex ${deployKey}` };

    // Create prompt record
    const createResp = await fetch(`${convexUrl}/api/mutation`, {
      method: "POST", headers,
      body: JSON.stringify({ path: "prompts:create", args: { scanId, question: args.question } }),
    });
    const promptId = (await createResp.json()).value;

    // Push trace action
    await fetch(`${convexUrl}/api/mutation`, {
      method: "POST", headers,
      body: JSON.stringify({ path: "actions:push", args: { scanId, type: "human_input_request", payload: { promptId, question: args.question } } }),
    });

    // Poll for answer (10 min timeout, 3s interval)
    for (let i = 0; i < 200; i++) {
      await new Promise(r => setTimeout(r, 3000));
      const resp = await fetch(`${convexUrl}/api/query`, {
        method: "POST", headers,
        body: JSON.stringify({ path: "prompts:get", args: { promptId } }),
      });
      const data = await resp.json();
      const prompt = data.value || data;
      if (prompt?.status === "answered") {
        return prompt.response || "(no response)";
      }
    }
    return "(no response — operator timed out)";
  },
})
'''


# Web scanning tools — each calls the local Playwright bridge at localhost:4097

def _make_bridge_tool(name: str, description: str, args_schema: str) -> str:
    """Generate a custom tool that calls the Playwright bridge HTTP server."""
    return f'''
import {{ tool }} from "@opencode-ai/plugin"

export default tool({{
  description: {repr(description)},
  args: {{ {args_schema} }},
  async execute(args) {{
    const resp = await fetch("http://localhost:4097/{name}", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(args),
    }});
    if (!resp.ok) return `Error: ${{resp.status}} ${{await resp.text()}}`;
    return await resp.text();
  }},
}})
'''

_WEB_TOOLS = {
    "navigate": _make_bridge_tool(
        "navigate",
        "Navigate the browser to a URL. Returns the page title and first 2000 chars of visible text.",
        'url: tool.schema.string().describe("URL to navigate to")',
    ),
    "act": _make_bridge_tool(
        "act",
        "Perform a browser action using natural language. Stagehand AI finds the right element and interacts with it. Examples: 'click the login button', 'fill the search box with test query'. For sensitive values use variables: instruction='fill password with %pass%', variables={pass: 'secret'}.",
        'instruction: tool.schema.string().describe("Natural language instruction for the action"), variables: tool.schema.record(tool.schema.string(), tool.schema.string()).optional().describe("Sensitive values as %name% placeholders — not sent to AI")',
    ),
    "observe": _make_bridge_tool(
        "observe",
        "Find interactive elements on the page using natural language. Returns actionable elements with descriptions.",
        'instruction: tool.schema.string().describe("What to look for, e.g. find all form inputs, find the login button")',
    ),
    "extract": _make_bridge_tool(
        "extract",
        "Extract structured data from the page using AI. Provide instruction and optionally a JSON schema.",
        'instruction: tool.schema.string().describe("What data to extract"), schema: tool.schema.record(tool.schema.string(), tool.schema.any()).optional().describe("JSON schema for output")',
    ),
    "get_page_content": _make_bridge_tool(
        "get_page_content",
        "Get the current page's HTML, links, forms, and interactive elements. Use this for detailed structural security analysis.",
        "",
    ),
    "execute_js": _make_bridge_tool(
        "execute_js",
        "Execute JavaScript in the browser. Use for checking cookies, response headers, testing XSS, DOM inspection.",
        'script: tool.schema.string().describe("JavaScript to execute")',
    ),
    "screenshot": _make_bridge_tool(
        "screenshot",
        "Capture a screenshot of the current page as visual evidence.",
        'label: tool.schema.string().describe("Brief label for what this screenshot captures")',
    ),
}


def _write_custom_tools(work_dir: str, scan_type: str = "oss"):
    """Write OpenCode custom tool definitions to .opencode/tools/."""
    import os

    tools_dir = os.path.join(work_dir, ".opencode", "tools")
    os.makedirs(tools_dir, exist_ok=True)

    # Always write submit_findings and ask_human
    with open(os.path.join(tools_dir, "submit_findings.ts"), "w") as f:
        f.write(_TOOL_SUBMIT_FINDINGS)
    with open(os.path.join(tools_dir, "ask_human.ts"), "w") as f:
        f.write(_TOOL_ASK_HUMAN)

    # Write web scanning tools (Playwright bridge callers)
    if scan_type == "web":
        for name, content in _WEB_TOOLS.items():
            with open(os.path.join(tools_dir, f"{name}.ts"), "w") as f:
                f.write(content)

    # Write package.json for Bun to resolve @opencode-ai/plugin
    with open(os.path.join(tools_dir, "package.json"), "w") as f:
        f.write('{"dependencies": {"@opencode-ai/plugin": "latest"}}')


async def _wait_for_opencode(port: int = 4096, timeout: int = 60):
    """Poll until OpenCode server is accepting connections."""
    import asyncio
    import httpx

    for _ in range(timeout * 2):
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.get(f"http://localhost:{port}/config", timeout=2)
                if resp.status_code == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"OpenCode server did not start within {timeout}s")


async def _stream_opencode_events(
    client,
    session_id: str,
    convex_url: str,
    deploy_key: str,
    scan_id: str,
    project_id: str,
    work_dir: str = "",
):
    """Subscribe to OpenCode SSE events and relay them to Convex as actions.

    OpenCode SSE event types:
    - message.part.updated: complete Part object at properties.part
    - message.part.delta: streaming token at properties.{field, delta, partID}
    - session.idle: agent finished processing
    - session.error: error occurred

    We use message.part.updated (fires when a part is finalized) for
    complete text/reasoning blocks and tool state changes.  We ignore
    message.part.delta (per-token streaming) to avoid flooding Convex.

    The /event endpoint is global (broadcasts ALL sessions). We filter
    by session_id client-side. If no meaningful event arrives for
    STALE_TIMEOUT seconds, we poll session status to detect dead sessions.
    """
    import json
    import time
    import httpx

    STALE_TIMEOUT = 300  # 5 minutes without a meaningful event → check session

    report_submitted = False
    seen_tool_calls = set()  # Track tool call IDs to avoid duplicate push
    seen_text_parts = set()  # Track text/reasoning part IDs already pushed
    last_meaningful_event = time.monotonic()

    def _extract_session_id(data: dict) -> str | None:
        """Extract sessionID from an OpenCode SSE event."""
        props = data.get("properties", {})
        # message.part.updated / message.part.delta → properties.part.sessionID
        part = props.get("part", {})
        if isinstance(part, dict) and part.get("sessionID"):
            return part["sessionID"]
        # session.* → properties.info.id or properties.sessionID
        info = props.get("info", {})
        if isinstance(info, dict) and info.get("id"):
            return info["id"]
        return props.get("sessionID")

    async def _check_session_alive() -> bool:
        """Poll session status — returns False if session is dead/errored."""
        try:
            resp = await client.get(f"/session/{session_id}", timeout=httpx.Timeout(10, connect=5))
            if resp.status_code != 200:
                return False
            # Also check /session/status for running state
            status_resp = await client.get("/session/status", timeout=httpx.Timeout(10, connect=5))
            if status_resp.status_code == 200:
                statuses = status_resp.json()
                if isinstance(statuses, dict):
                    sess_status = statuses.get(session_id, {})
                    if isinstance(sess_status, dict):
                        # If status is "idle" or missing, session has stopped
                        return sess_status.get("status") not in (None, "idle", "error")
                    elif isinstance(sess_status, str):
                        return sess_status not in ("idle", "error", "")
            return True  # Can't determine, assume alive
        except Exception:
            return True  # Network error, don't kill prematurely

    try:
        async with client.stream(
            "GET", "/event",
            timeout=httpx.Timeout(STALE_TIMEOUT + 60, connect=30),
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    # Check staleness on non-data lines (heartbeats, comments)
                    if time.monotonic() - last_meaningful_event > STALE_TIMEOUT:
                        alive = await _check_session_alive()
                        if not alive:
                            await _push_action(convex_url, deploy_key, scan_id, "observation",
                                "OpenCode session appears dead (no activity). Recovering...")
                            break
                    continue

                raw = line[5:].strip()
                if not raw:
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")

                # Filter by session_id (the /event endpoint is global)
                evt_session = _extract_session_id(data)
                if evt_session and evt_session != session_id:
                    continue

                # --- Complete part (text, reasoning, tool) ---
                if event_type == "message.part.updated":
                    last_meaningful_event = time.monotonic()
                    # Part is nested under properties.part
                    part = data.get("properties", {}).get("part", {})
                    part_type = part.get("type", "")
                    part_id = part.get("id", "")

                    if part_type in ("text", "reasoning"):
                        if part_id in seen_text_parts:
                            continue
                        seen_text_parts.add(part_id)
                        text = part.get("text", "")
                        if text.strip():
                            await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

                    elif part_type == "tool":
                        tool_name = part.get("tool", "unknown")
                        call_id = part.get("callID", part.get("id", ""))
                        state = part.get("state", {})
                        status = state.get("status", "") if isinstance(state, dict) else str(state)
                        input_data = state.get("input", {}) if isinstance(state, dict) else {}
                        title = state.get("title", "") if isinstance(state, dict) else ""

                        # Build summary matching Claude agent format:
                        # e.g. "Reading src/server.rs" not just "read"
                        def _tool_summary(tool, title, inp):
                            if title:
                                return title
                            # Fallback: build from tool name + input args
                            args_str = ", ".join(
                                f"{k}={repr(v)[:60]}" for k, v in inp.items()
                            ) if isinstance(inp, dict) and inp else ""
                            return f"{tool}({args_str})" if args_str else tool

                        # Push tool_call when first seen
                        if status in ("running", "pending") and call_id not in seen_tool_calls:
                            seen_tool_calls.add(call_id)
                            await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                                "tool": tool_name,
                                "summary": _tool_summary(tool_name, title, input_data),
                                "input": input_data if isinstance(input_data, dict) else {},
                            })

                        # Push tool_result when completed
                        elif status == "completed":
                            output = state.get("output", "") if isinstance(state, dict) else ""
                            content = str(output)[:50000]
                            summary = title or f"{tool_name} returned {len(content):,} chars"
                            await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                                "tool": tool_name,
                                "summary": f"{summary} ({len(content):,} chars)",
                                "content": content,
                            })
                            if tool_name == "submit_findings":
                                report_submitted = True

                        elif status == "error":
                            error = state.get("error", "unknown error") if isinstance(state, dict) else "unknown error"
                            await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                                "tool": tool_name,
                                "summary": f"{tool_name} failed: {str(error)[:80]}",
                                "content": str(error),
                            })

                # --- Session completion ---
                elif event_type == "session.idle":
                    last_meaningful_event = time.monotonic()
                    break

                elif event_type == "session.error":
                    last_meaningful_event = time.monotonic()
                    error_msg = data.get("properties", {}).get("error", str(data))
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        f"Rem encountered an error: {str(error_msg)[:300]}")
                    break

                # Stale check on delta events (these arrive frequently but
                # don't reset the meaningful timer — they're just streaming tokens)
                elif event_type == "message.part.delta":
                    if time.monotonic() - last_meaningful_event > STALE_TIMEOUT:
                        alive = await _check_session_alive()
                        if not alive:
                            await _push_action(convex_url, deploy_key, scan_id, "observation",
                                "OpenCode session appears dead (streaming deltas but no progress). Recovering...")
                            break

    except httpx.ReadTimeout:
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            f"SSE stream timed out after {STALE_TIMEOUT + 60}s with no data. Recovering...")
    except Exception as e:
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            f"SSE stream error: {str(e)[:200]}")

    # --- Post-SSE fallback: fetch session messages to catch anything missed ---
    # Some models (especially Nemotron) produce output that only appears in
    # message.part.delta (streaming tokens) without a corresponding
    # message.part.updated event before session.idle fires.
    try:
        resp = await client.get(f"/session/{session_id}/message")
        if resp.status_code == 200:
            messages = resp.json()
            if isinstance(messages, list):
                for msg in messages:
                    role = msg.get("role", "")
                    if role != "assistant":
                        continue
                    parts = msg.get("parts", [])
                    for part in parts:
                        part_type = part.get("type", "")
                        part_id = part.get("id", "")

                        if part_type in ("text", "reasoning"):
                            if part_id in seen_text_parts:
                                continue
                            seen_text_parts.add(part_id)
                            text = part.get("text", "")
                            if text.strip():
                                action_type = "reasoning" if part_type == "reasoning" else "reasoning"
                                await _push_action(convex_url, deploy_key, scan_id, action_type, text.strip())

                        elif part_type == "tool":
                            call_id = part.get("callID", part.get("id", ""))
                            tool_name = part.get("tool", "unknown")
                            state = part.get("state", {})
                            status = state.get("status", "") if isinstance(state, dict) else ""
                            title = state.get("title", "") if isinstance(state, dict) else ""
                            input_data = state.get("input", {}) if isinstance(state, dict) else {}

                            if call_id not in seen_tool_calls:
                                seen_tool_calls.add(call_id)
                                summary = title or tool_name
                                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                                    "tool": tool_name,
                                    "summary": summary,
                                    "input": input_data if isinstance(input_data, dict) else {},
                                })

                            if status == "completed":
                                output = state.get("output", "") if isinstance(state, dict) else ""
                                content = str(output)[:50000]
                                summary = title or f"{tool_name} returned {len(content):,} chars"
                                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                                    "tool": tool_name,
                                    "summary": f"{summary} ({len(content):,} chars)",
                                    "content": content,
                                })
                                if tool_name == "submit_findings":
                                    report_submitted = True
    except Exception as e:
        # Non-fatal — SSE may have captured everything already
        pass

    if not report_submitted:
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            "Scanning complete. Handing off to report writer...")
        await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)


async def _run_opencode_agent(
    scan_id: str,
    project_id: str,
    model: str,
    work_dir: str,
    file_list: list[str],
    repo_url: str,
    convex_url: str,
    deploy_key: str,
):
    """Run security scan using OpenCode SDK (GLM-5, Kimi K2.5, etc.)."""
    import asyncio
    import json
    import os
    import subprocess
    import httpx
    import traceback

    model_label = _get_opencode_model_label(model)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        f"Rem ({model_label}) initializing OpenCode environment...")

    # 1. Write opencode.json with provider config
    config = _build_opencode_config(model)
    config_path = os.path.join(work_dir, "opencode.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # 2. Set environment variables for custom tools (Convex connection)
    env = os.environ.copy()
    env["CONVEX_URL"] = convex_url
    env["CONVEX_DEPLOY_KEY"] = deploy_key
    env["SCAN_ID"] = scan_id
    env["PROJECT_ID"] = project_id

    # 3. Write custom tools to .opencode/tools/ and install dependencies
    _write_custom_tools(work_dir, scan_type="oss")
    subprocess.run(
        ["bun", "install"],
        cwd=os.path.join(work_dir, ".opencode", "tools"),
        env=env,
        capture_output=True,
        timeout=60,
    )

    # 4. Start opencode serve
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        f"Starting OpenCode server with {model_label}...")

    proc = subprocess.Popen(
        ["opencode", "serve", "--port", "4096"],
        cwd=work_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        await _wait_for_opencode(port=4096)
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            f"OpenCode server ready — {model_label} agent active")

        async with httpx.AsyncClient(
            base_url="http://localhost:4096",
            timeout=httpx.Timeout(30, connect=10),
        ) as client:
            # 5. Create session
            resp = await client.post("/session", json={})
            resp.raise_for_status()
            session_data = resp.json()
            session_id = session_data.get("id", session_data.get("ID", ""))

            if not session_id:
                # Try to extract from nested response
                if isinstance(session_data, dict):
                    for v in session_data.values():
                        if isinstance(v, str) and len(v) > 5:
                            session_id = v
                            break
                if not session_id:
                    raise RuntimeError(f"Could not extract session ID from: {session_data}")

            # 6. Build and send the scan prompt
            files_preview = "\n".join(
                f.replace(work_dir + "/", "") for f in file_list[:100]
            )
            system_prompt = f"""You are Rem, a security researcher performing a vulnerability audit on a codebase.

Repository: {repo_url}

Your task:
1. Analyze the codebase for security vulnerabilities using the built-in read, grep, and glob tools
2. Focus on: injection flaws, authentication issues, data exposure, misconfigurations, dependency vulnerabilities
3. For each finding, include a code_snippet field with the exact vulnerable code lines
4. When done, call submit_findings with your structured report

Be thorough but precise. Only report real vulnerabilities, not style issues.

Files in repository:
{files_preview}"""

            user_msg = "Analyze this codebase for security vulnerabilities. Read key files, identify attack surfaces, and produce a structured security report using the submit_findings tool."

            # 7. Subscribe to SSE FIRST, then send prompt asynchronously.
            # /message blocks until model finishes — events would be lost.
            # prompt_async returns immediately; events stream via /event.
            sse_task = asyncio.create_task(
                _stream_opencode_events(
                    client, session_id,
                    convex_url, deploy_key,
                    scan_id, project_id,
                    work_dir,
                )
            )

            # Give SSE a moment to connect before sending prompt
            await asyncio.sleep(0.5)

            await _push_action(convex_url, deploy_key, scan_id, "reasoning",
                f"Rem ({model_label}) starting security analysis...")

            prompt_resp = await client.post(
                f"/session/{session_id}/prompt_async",
                json={
                    "system": system_prompt,
                    "parts": [{"type": "text", "text": user_msg}],
                },
                timeout=httpx.Timeout(30, connect=10),
            )
            prompt_resp.raise_for_status()

            # Wait for SSE stream to finish (session.idle, error, or stale timeout)
            # Hard cap at 45 minutes — no scan should run longer than this
            try:
                await asyncio.wait_for(sse_task, timeout=2700)
            except asyncio.TimeoutError:
                await _push_action(convex_url, deploy_key, scan_id, "observation",
                    "Scan hit 45-minute hard limit. Compiling findings so far...")

    except Exception as e:
        # Capture stderr from the OpenCode process for debugging
        stderr_text = ""
        try:
            stderr_text = proc.stderr.read().decode(errors="replace")[:500] if proc.stderr else ""
        except Exception:
            pass
        detail = f"{e}" + (f" | stderr: {stderr_text}" if stderr_text else "")
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            f"OpenCode agent error: {detail[:500]}")
        # Fall back to report compilation if we got any data
        await _compile_report(convex_url, deploy_key, scan_id, project_id, work_dir=work_dir)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------------------
# Stagehand browser session (shared by both Claude and OpenCode web paths)
# ---------------------------------------------------------------------------

async def _start_stagehand_browser(target_url: str):
    """Start Stagehand local mode with Haiku for AI-powered browser automation.

    Returns (session, pw_page, cleanup) where:
    - session: Stagehand session — use for act/observe/extract/navigate
    - pw_page: raw Playwright page via CDP — use for execute_js/screenshot
    - cleanup: async callable to tear everything down
    """
    from stagehand import AsyncStagehand
    from playwright.async_api import async_playwright

    # CHROME_PATH is baked into the Modal image env via symlink at /usr/local/bin/stagehand-chrome.
    # The symlink is created at image build time pointing to Playwright's actual Chromium binary.
    chrome_path = os.environ.get("CHROME_PATH", "/usr/local/bin/stagehand-chrome")

    # Stagehand local mode: SEA binary (embedded Node.js server) starts Chrome + handles
    # AI element resolution via Haiku on Bedrock. AWS creds flow through env vars.
    client = AsyncStagehand(
        server="local",
        model_api_key="bedrock",  # placeholder — bedrock uses AWS credential chain, not API key
        local_chrome_path=chrome_path,
        local_ready_timeout_s=60.0,
    )
    session = await client.sessions.start(
        model_name="bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
        browser={
            "type": "local",
            "launchOptions": {
                "executablePath": chrome_path,
                "headless": True,
                "args": ["--no-sandbox", "--disable-setuid-sandbox"],
            },
        },
    )

    # Navigate to target via Stagehand
    await session.navigate(url=target_url)

    # Connect raw Playwright to the SAME browser via CDP for execute_js/screenshot
    pw_manager = async_playwright()
    pw = await pw_manager.__aenter__()
    browser = await pw.chromium.connect_over_cdp(session.connect_url)
    context = browser.contexts[0]
    pw_page = context.pages[0] if context.pages else await context.new_page()

    async def cleanup():
        for fn in [
            lambda: session.end(),
            lambda: client.close(),
            lambda: pw_manager.__aexit__(None, None, None),
        ]:
            try:
                await fn()
            except Exception:
                pass

    return session, pw_page, cleanup


# ---------------------------------------------------------------------------
# Stagehand bridge HTTP server (for OpenCode web scanning)
# ---------------------------------------------------------------------------

async def _run_stagehand_bridge(session, pw_page, convex_url: str, deploy_key: str, scan_id: str, port: int = 4097):
    """Start an HTTP server exposing Stagehand + Playwright operations for OpenCode tools.

    AI-powered tools (act, observe, extract, navigate) go through Stagehand session.
    Raw tools (execute_js, screenshot, get_page_content) go through Playwright page via CDP.
    Returns the aiohttp server runner for cleanup.
    """
    from aiohttp import web
    import json

    async def handle_navigate(request):
        data = await request.json()
        url = data.get("url", "")
        try:
            await session.navigate(url=url)
            title = await pw_page.title()
            text = await pw_page.inner_text("body")
            return web.Response(text=f"Navigated to {pw_page.url}\nTitle: {title}\n\n{text[:2000]}")
        except Exception as e:
            return web.Response(text=f"Navigation failed: {e}", status=500)

    async def handle_act(request):
        data = await request.json()
        instruction = data.get("instruction", "")
        variables = data.get("variables")
        try:
            kwargs = {"input": instruction}
            if variables:
                kwargs["variables"] = variables
            result = await session.act(**kwargs)
            msg = result.data.result.message if result.data and result.data.result else "Action completed"
            success = result.data.result.success if result.data and result.data.result else True
            return web.Response(text=f"{'Success' if success else 'Failed'}: {msg}. Now at {pw_page.url}")
        except Exception as e:
            return web.Response(text=f"Act failed: {e}", status=500)

    async def handle_observe(request):
        data = await request.json()
        instruction = data.get("instruction", "")
        try:
            result = await session.observe(instruction=instruction)
            elements = result.data.result if result.data else []
            items = []
            for el in (elements or []):
                d = el.to_dict(exclude_none=True) if hasattr(el, "to_dict") else str(el)
                items.append(d)
            return web.Response(
                text=json.dumps(items[:20], indent=2, default=str),
                content_type="application/json",
            )
        except Exception as e:
            return web.Response(text=f"Observe failed: {e}", status=500)

    async def handle_extract(request):
        data = await request.json()
        instruction = data.get("instruction", "")
        schema = data.get("schema")
        try:
            kwargs = {"instruction": instruction}
            if schema:
                kwargs["schema"] = schema
            result = await session.extract(**kwargs)
            extracted = result.data.result if result.data else {}
            return web.Response(
                text=json.dumps(extracted, indent=2, default=str),
                content_type="application/json",
            )
        except Exception as e:
            return web.Response(text=f"Extract failed: {e}", status=500)

    async def handle_get_page_content(request):
        try:
            content = await pw_page.evaluate("""() => {
                const result = {
                    url: location.href,
                    title: document.title,
                    forms: [],
                    links: [],
                    inputs: [],
                    meta: [],
                };
                document.querySelectorAll('form').forEach((f, i) => {
                    result.forms.push({
                        action: f.action, method: f.method, id: f.id,
                        fields: Array.from(f.querySelectorAll('input,select,textarea')).map(el => ({
                            tag: el.tagName, type: el.type, name: el.name, id: el.id, placeholder: el.placeholder
                        }))
                    });
                });
                Array.from(document.querySelectorAll('a[href]')).slice(0, 50).forEach(a => {
                    result.links.push({href: a.href, text: a.textContent?.trim().slice(0, 60)});
                });
                document.querySelectorAll('input:not(form input), textarea:not(form textarea)').forEach(el => {
                    result.inputs.push({tag: el.tagName, type: el.type, name: el.name, id: el.id});
                });
                document.querySelectorAll('meta').forEach(m => {
                    if (m.name || m.httpEquiv) result.meta.push({name: m.name, httpEquiv: m.httpEquiv, content: m.content});
                });
                return result;
            }""")
            html = await pw_page.content()
            content["html_preview"] = html[:8000]
            return web.Response(text=json.dumps(content, indent=2, default=str),
                                content_type="application/json")
        except Exception as e:
            return web.Response(text=f"Failed to read page: {e}", status=500)

    async def handle_execute_js(request):
        data = await request.json()
        script = data.get("script", "")
        try:
            result = await pw_page.evaluate(script)
            return web.Response(text=json.dumps(result, indent=2, default=str) if result is not None else "undefined")
        except Exception as e:
            return web.Response(text=f"JS execution failed: {e}", status=500)

    async def handle_screenshot(request):
        data = await request.json()
        label = data.get("label", "screenshot")
        try:
            screenshot_bytes = await pw_page.screenshot(type="png")
            storage_id = await _upload_screenshot(convex_url, deploy_key, screenshot_bytes)
            await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                "tool": "screenshot",
                "summary": f"Captured: {label}",
                "storageId": storage_id,
            })
            return web.Response(text=f"Screenshot captured: {label} (storageId: {storage_id})")
        except Exception as e:
            return web.Response(text=f"Screenshot failed: {e}", status=500)

    app = web.Application()
    app.router.add_post("/navigate", handle_navigate)
    app.router.add_post("/act", handle_act)
    app.router.add_post("/observe", handle_observe)
    app.router.add_post("/extract", handle_extract)
    app.router.add_post("/get_page_content", handle_get_page_content)
    app.router.add_post("/execute_js", handle_execute_js)
    app.router.add_post("/screenshot", handle_screenshot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()
    return runner


async def _run_web_opencode_agent(
    scan_id: str,
    project_id: str,
    model: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    stagehand_session,
    pw_page,
    work_dir: str,
    convex_url: str,
    deploy_key: str,
):
    """Run web pentesting using OpenCode SDK with Stagehand bridge."""
    import asyncio
    import json
    import os
    import subprocess
    import httpx

    model_label = _get_opencode_model_label(model)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        f"Rem ({model_label}) initializing OpenCode for web scanning...")

    # 1. Start Stagehand bridge HTTP server on port 4097
    bridge_runner = await _run_stagehand_bridge(stagehand_session, pw_page, convex_url, deploy_key, scan_id)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Stagehand bridge server active on port 4097")

    try:
        # 2. Write opencode.json with provider config
        config = _build_opencode_config(model)
        with open(os.path.join(work_dir, "opencode.json"), "w") as f:
            json.dump(config, f, indent=2)

        # 3. Set environment variables for custom tools
        env = os.environ.copy()
        env["CONVEX_URL"] = convex_url
        env["CONVEX_DEPLOY_KEY"] = deploy_key
        env["SCAN_ID"] = scan_id
        env["PROJECT_ID"] = project_id

        # 4. Write custom tools (web mode includes Playwright bridge tools) and install deps
        _write_custom_tools(work_dir, scan_type="web")
        subprocess.run(
            ["bun", "install"],
            cwd=os.path.join(work_dir, ".opencode", "tools"),
            env=env,
            capture_output=True,
            timeout=60,
        )

        # 5. Start opencode serve
        await _push_action(convex_url, deploy_key, scan_id, "observation",
            f"Starting OpenCode server with {model_label}...")

        proc = subprocess.Popen(
            ["opencode", "serve", "--port", "4096"],
            cwd=work_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            await _wait_for_opencode(port=4096)
            await _push_action(convex_url, deploy_key, scan_id, "observation",
                f"OpenCode server ready — {model_label} agent active for web scanning")

            async with httpx.AsyncClient(
                base_url="http://localhost:4096",
                timeout=httpx.Timeout(30, connect=10),
            ) as client:
                # 6. Create session
                resp = await client.post("/session", json={})
                resp.raise_for_status()
                session_data = resp.json()
                session_id = session_data.get("id", session_data.get("ID", ""))

                if not session_id:
                    if isinstance(session_data, dict):
                        for v in session_data.values():
                            if isinstance(v, str) and len(v) > 5:
                                session_id = v
                                break
                    if not session_id:
                        raise RuntimeError(f"Could not extract session ID from: {session_data}")

                # 7. Build scan prompt
                auth_info = ""
                if test_account:
                    username = test_account.get("username", "")
                    password = test_account.get("password", "")
                    auth_info = f"""Test account provided:
  Username: {username}
  Password: {password}

Scan BOTH unauthenticated and authenticated surfaces:
1. First pass: unauthenticated — check public attack surface, headers, exposed endpoints
2. Then login with the test account
3. Second pass: authenticated — explore protected areas, test privilege escalation, session management"""
                else:
                    auth_info = "No test credentials provided. Scan unauthenticated attack surface only."

                context_info = ""
                if user_context:
                    context_info = f"""
Operator notes (from the person who set up this scan):
{user_context}

Pay close attention to these notes — they contain insider knowledge about the target."""

                system_prompt = f"""You are Rem, a security researcher performing a web application penetration test.

Target: {target_url}
{auth_info}
{context_info}

Human-in-the-loop:
You have an ask_human tool. The operator is watching the scan live and can help you. When you hit something you can't get past alone — 2FA codes, email verification, CAPTCHAs, bot detection — use ask_human.

Browser tools (powered by Stagehand AI — use natural language, NOT CSS selectors):
- navigate(url): go to a URL
- act(instruction): perform browser actions in natural language — "click the login button", "fill the email field with test@example.com". For passwords/secrets, use variables: instruction="fill password with %pass%", variables={{pass: "secret"}}
- observe(instruction): find interactive elements — "find all form inputs", "find the submit button"
- extract(instruction, schema): extract structured data from the page
- get_page_content(): detailed HTML/form/link/meta analysis for security review
- execute_js(script): run JavaScript (cookies, headers, XSS tests, DOM)
- screenshot(label): capture visual evidence

Methodology:
1. Use observe and get_page_content to understand the page — forms, inputs, links
2. Check security headers and cookies via execute_js
3. Crawl key pages — use navigate + observe to explore forms, login, search, API endpoints, admin paths
4. Actively test for vulnerabilities:
   - XSS: inject payloads via act("fill the search field with <script>alert(1)</script>") and navigate to URL params
   - SQL injection: test inputs with act("fill the field with ' OR 1=1 --")
   - Auth bypass: navigate to /admin, /api/users, modify IDs in URLs
   - CSRF: check if forms have anti-CSRF tokens (get_page_content)
   - Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
   - Cookie flags: HttpOnly, Secure, SameSite
   - Info disclosure: error messages, stack traces, .env, .git, robots.txt
   - CORS: check Access-Control-Allow-Origin via execute_js
5. Take screenshots of important findings as visual evidence
6. Submit your report with all findings using submit_findings

Be thorough and aggressive. Only report confirmed or highly probable vulnerabilities."""

                user_msg = f"Perform a comprehensive penetration test on {target_url}. Actively probe for vulnerabilities, take screenshots of findings, and produce a structured security report using the submit_findings tool."

                # 8. Subscribe to SSE FIRST, then send prompt asynchronously.
                sse_task = asyncio.create_task(
                    _stream_opencode_events(
                        client, session_id,
                        convex_url, deploy_key,
                        scan_id, project_id,
                        work_dir,
                    )
                )

                await asyncio.sleep(0.5)

                await _push_action(convex_url, deploy_key, scan_id, "reasoning",
                    f"Rem ({model_label}) starting web penetration test...")

                prompt_resp = await client.post(
                    f"/session/{session_id}/prompt_async",
                    json={
                        "system": system_prompt,
                        "parts": [{"type": "text", "text": user_msg}],
                    },
                    timeout=httpx.Timeout(30, connect=10),
                )
                prompt_resp.raise_for_status()

                # Wait for SSE stream (session.idle, error, or stale timeout)
                try:
                    await asyncio.wait_for(sse_task, timeout=2700)
                except asyncio.TimeoutError:
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        "Scan hit 45-minute hard limit. Compiling findings so far...")

        except Exception as e:
            stderr_text = ""
            try:
                stderr_text = proc.stderr.read().decode(errors="replace")[:500] if proc.stderr else ""
            except Exception:
                pass
            detail = f"{e}" + (f" | stderr: {stderr_text}" if stderr_text else "")
            await _push_action(convex_url, deploy_key, scan_id, "observation",
                f"OpenCode web agent error: {detail[:500]}")
            await _compile_report(convex_url, deploy_key, scan_id, project_id)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    finally:
        await bridge_runner.cleanup()


# ---------------------------------------------------------------------------
# OpenCode Modal functions
# ---------------------------------------------------------------------------

@app.function(
    image=opencode_sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_oss_scan_opencode(
    scan_id: str,
    project_id: str,
    repo_url: str,
    model: str,
    convex_url: str,
    convex_deploy_key: str,
    storage_id: str = "",
):
    """Run an OSS security scan using OpenCode (GLM-5, Kimi K2.5, etc.)."""
    import subprocess
    import os

    work_dir = "/root/target"

    if storage_id:
        await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Rem is downloading the uploaded code...")
        url = await _get_storage_url(convex_url, convex_deploy_key, storage_id)
        subprocess.run(["curl", "-sL", "-o", "/tmp/repo.tar.gz", url], check=True, capture_output=True)
        os.makedirs(work_dir, exist_ok=True)
        subprocess.run(["tar", "xzf", "/tmp/repo.tar.gz", "-C", work_dir], check=True, capture_output=True)
    else:
        await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Rem is cloning the repository...")
        subprocess.run(
            ["git", "clone", "--depth=1", repo_url, work_dir],
            check=True,
            capture_output=True,
        )

    result = subprocess.run(
        ["find", work_dir, "-type", "f", "-not", "-path", "*/.git/*"],
        capture_output=True,
        text=True,
    )
    file_list = result.stdout.strip().split("\n")[:200]

    source_label = repo_url if repo_url else "uploaded tarball"
    await _push_action(
        convex_url, convex_deploy_key, scan_id, "observation",
        f"Rem loaded {source_label} — {len(file_list)} files indexed"
    )

    await _run_opencode_agent(
        scan_id, project_id, model, work_dir, file_list,
        repo_url, convex_url, convex_deploy_key,
    )


@app.function(
    image=opencode_web_sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_web_scan_opencode(
    scan_id: str,
    project_id: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    model: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run a web pentesting scan using OpenCode (GLM-5, Kimi K2.5, etc.) with Stagehand."""
    work_dir = "/root/target"
    import os
    os.makedirs(work_dir, exist_ok=True)

    model_label = _get_opencode_model_label(model)

    try:
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            f"Rem ({model_label}) launching Stagehand browser targeting {target_url}...",
        )

        session, pw_page, cleanup = await _start_stagehand_browser(target_url)

        try:
            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Browser active (Stagehand + Haiku) — loaded {pw_page.url}",
            )

            await _run_web_opencode_agent(
                scan_id, project_id, model, target_url,
                test_account, user_context, session, pw_page, work_dir,
                convex_url, convex_deploy_key,
            )
        finally:
            await cleanup()

    except Exception as e:
        try:
            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Rem encountered an error: {e}",
            )
            await _convex_mutation(convex_url, convex_deploy_key, "scans:updateStatus", {
                "scanId": scan_id,
                "status": "failed",
                "error": str(e)[:500],
            })
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Web pentesting scan (Stagehand + headless Chromium)
# ---------------------------------------------------------------------------

@app.function(
    image=web_sandbox_image,
    timeout=60 * MINUTES,
    secrets=[modal.Secret.from_name("re-zero-keys")],
)
async def run_web_scan(
    scan_id: str,
    project_id: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    model: str = "claude-opus-4.6",
    convex_url: str = "",
    convex_deploy_key: str = "",
):
    """Run a web application pentesting scan with Stagehand + headless Chromium."""
    try:
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            f"Rem is launching Stagehand browser targeting {target_url}...",
        )

        session, pw_page, cleanup = await _start_stagehand_browser(target_url)

        try:
            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Browser active (Stagehand + Haiku) — loaded {pw_page.url}",
            )

            await _run_web_claude_agent(
                scan_id, project_id, target_url, test_account,
                user_context, session, pw_page, convex_url, convex_deploy_key,
                model=model,
            )
        finally:
            await cleanup()

    except Exception as e:
        # Surface error to the frontend
        try:
            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Rem encountered an error: {e}",
            )
            await _convex_mutation(convex_url, convex_deploy_key, "scans:updateStatus", {
                "scanId": scan_id,
                "status": "failed",
                "error": str(e)[:500],
            })
        except Exception:
            pass  # best-effort error reporting
        raise


async def _run_web_claude_agent(
    scan_id: str,
    project_id: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    stagehand_session,
    pw_page,
    convex_url: str,
    deploy_key: str,
    model: str = "claude-opus-4.6",
):
    """Run web pentesting using Claude with Stagehand (AI browser) + raw Playwright tools."""
    import json

    client = _get_anthropic_client()

    auth_info = ""
    if test_account:
        username = test_account.get("username", "")
        password = test_account.get("password", "")
        auth_info = f"""Test account provided:
  Username: {username}
  Password: {password}

Scan BOTH unauthenticated and authenticated surfaces:
1. First pass: unauthenticated — check public attack surface, headers, exposed endpoints
2. Then login with the test account (use act with variables for password: instruction="fill password with %pass%", variables={{"pass": "{password}"}})
3. Second pass: authenticated — explore protected areas, test privilege escalation, session management"""
    else:
        auth_info = "No test credentials provided. Scan unauthenticated attack surface only."

    context_info = ""
    if user_context:
        context_info = f"""
Operator notes (from the person who set up this scan):
{user_context}

Pay close attention to these notes — they contain insider knowledge about the target."""

    system_prompt = f"""You are Rem, a security researcher performing a web application penetration test.

Target: {target_url}
{auth_info}
{context_info}

Human-in-the-loop:
You have an ask_human tool. The operator is watching the scan live and can help you. When you hit something you can't get past alone — 2FA codes, email verification, CAPTCHAs, bot detection, or any authentication challenge — use ask_human to request what you need. Don't skip these and move on to unauthenticated testing; the whole point of having test credentials is to test the authenticated surface. Ask, wait for the response, then continue.

Browser tools (powered by Stagehand AI — use natural language, NOT CSS selectors):
- navigate(url): go to a URL, returns page title and visible text
- act(instruction, variables?): perform browser actions in natural language — "click the login button", "fill the search box with test query". For passwords/secrets, use variables: instruction="fill password with %pass%", variables={{"pass": "secret"}}
- observe(instruction): find interactive elements — "find all form inputs", "find the submit button"
- extract(instruction, schema?): extract structured data from the page using AI
- get_page_content(): detailed HTML/form/link/meta analysis for security review
- execute_js(script): run JavaScript directly (cookies, headers, XSS tests, DOM)
- screenshot(label): capture visual evidence

Methodology:
1. Use observe and get_page_content to understand the page — forms, inputs, links
2. Check security headers and cookies via execute_js
3. Crawl key pages — use navigate + observe to explore forms, login, search, API endpoints, admin paths
4. Actively test for vulnerabilities:
   - XSS: inject payloads via act("fill the search field with <script>alert(1)</script>") and navigate to URL params
   - SQL injection: test inputs with act("fill the field with ' OR 1=1 --")
   - Auth bypass: navigate to /admin, /api/users, modify IDs in URLs
   - CSRF: check if forms have anti-CSRF tokens (get_page_content)
   - Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
   - Cookie flags: HttpOnly, Secure, SameSite
   - Info disclosure: error messages, stack traces, .env, .git, robots.txt
   - CORS: check Access-Control-Allow-Origin via execute_js
   - Directory traversal: try ../../etc/passwd in file parameters
5. Take screenshots of important findings as visual evidence
6. Submit your report with all findings

You have Firecrawl tools for supplementary web research (CVE lookups, documentation).

Be thorough and aggressive in testing. Only report confirmed or highly probable vulnerabilities.

Report format:
When you call submit_findings, each vulnerability should be its own entry in the findings array — don't consolidate them into the summary. The summary is just a brief overview (2-3 sentences). Each finding should include title, severity, description, location (URL/page), recommendation, and code_snippet (the actual headers, HTML, JS, or response content that demonstrates the issue). The richer each finding is, the more useful the report."""

    await _push_action(convex_url, deploy_key, scan_id, "reasoning",
        "Rem starting web penetration test...")

    messages = [{"role": "user", "content": f"Perform a comprehensive penetration test on {target_url}. Actively probe for vulnerabilities, take screenshots of findings, and produce a structured security report."}]

    tools = [
        {
            "name": "navigate",
            "description": "Navigate the browser to a URL. Returns the page title and first 2000 chars of visible text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                },
                "required": ["url"],
            },
        },
        {
            "name": "act",
            "description": "Perform a browser action using natural language. Stagehand AI finds the right element and interacts with it. Examples: 'click the login button', 'fill the search box with test query', 'select the first dropdown option'. For sensitive values like passwords, use the variables parameter — these are NOT sent to the browser AI.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "Natural language instruction for the browser action"},
                    "variables": {
                        "type": "object",
                        "description": "Sensitive values referenced as %name% in instruction. Example: instruction='fill password with %pass%', variables={'pass': 'secret123'}",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["instruction"],
            },
        },
        {
            "name": "observe",
            "description": "Find interactive elements on the current page using natural language. Returns a list of actionable elements with descriptions. Use this to understand what's clickable, fillable, or interactive.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "What to look for, e.g. 'find all form inputs', 'find the login button', 'find navigation links'"},
                },
                "required": ["instruction"],
            },
        },
        {
            "name": "extract",
            "description": "Extract structured data from the current page using AI. Provide a natural language instruction and optionally a JSON schema for the output format.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "What data to extract, e.g. 'extract all form fields and their types'"},
                    "schema": {
                        "type": "object",
                        "description": "JSON schema for the extracted data structure",
                    },
                },
                "required": ["instruction"],
            },
        },
        {
            "name": "get_page_content",
            "description": "Get the current page's HTML, links, forms, inputs, and meta tags. Use for detailed security-focused structural analysis.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "execute_js",
            "description": "Execute JavaScript in the browser. Use for checking cookies, response headers, testing XSS, DOM inspection. Return values to see results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "JavaScript to execute. Use 'return' to get values back."},
                },
                "required": ["script"],
            },
        },
        {
            "name": "screenshot",
            "description": "Capture a screenshot of the current page as visual evidence",
            "input_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Brief label for what this screenshot captures"},
                },
                "required": ["label"],
            },
        },
        {
            "name": "submit_findings",
            "description": "Submit the final security report",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "description": {"type": "string"},
                                "location": {"type": "string", "description": "URL path or page where the vulnerability was found"},
                                "recommendation": {"type": "string"},
                                "code_snippet": {"type": "string", "description": "Relevant HTML, JS, or HTTP headers showing the vulnerability"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        },
        {
            "name": "ask_human",
            "description": "Ask the human operator a question and wait for their response. Use this when you need information only a human can provide: 2FA codes, CAPTCHAs, login instructions, clarification about the target, or any situation where you're stuck and need human guidance.",
            "cache_control": {"type": "ephemeral"},
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the operator. Be specific about what you need and why."},
                },
                "required": ["question"],
            },
        },
    ]

    # Convert system prompt to content block format for prompt caching.
    system_cached = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    mcp_tools = [{"type": "mcp_toolset", "mcp_server_name": s["name"]} for s in MCP_SERVERS]

    turn = 0
    while True:
        turn += 1

        # MCP servers can have transient failures — retry, then fall back without them.
        # Bedrock doesn't support MCP beta API, so use standard messages.create() directly.
        response = None
        if _use_bedrock():
            response = client.messages.create(
                model=_get_model_id(model),
                max_tokens=4096,
                system=system_cached,
                tools=tools,
                messages=messages,
            )
        else:
            for attempt in range(3):
                try:
                    response = client.beta.messages.create(
                        model=model,
                        max_tokens=4096,
                        system=system_cached,
                        tools=[*tools, *mcp_tools] if attempt < 2 else tools,
                        mcp_servers=MCP_SERVERS if attempt < 2 else [],
                        messages=messages,
                        betas=["mcp-client-2025-11-20"],
                    )
                    break
                except Exception as e:
                    if attempt < 2 and "MCP" in str(e):
                        import asyncio
                        await asyncio.sleep(2)
                        continue
                    raise

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Push text/reasoning blocks
        text_blocks = [b.text for b in assistant_content if hasattr(b, "text") and b.type == "text"]
        for text in text_blocks:
            if text.strip():
                await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

        # Push MCP tool calls/results to trace
        mcp_tool_names = {}
        for block in assistant_content:
            if block.type == "mcp_tool_use":
                mcp_tool_names[block.id] = block.name

        for block in assistant_content:
            if block.type == "mcp_tool_use":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": block.name,
                    "summary": f"{block.name}({', '.join(f'{k}={repr(v)[:60]}' for k, v in (block.input or {}).items())})"[:120],
                    "input": block.input,
                })
            elif block.type == "mcp_tool_result":
                tool_name = mcp_tool_names.get(block.tool_use_id, "mcp")
                content_text = ""
                if hasattr(block, "content") and block.content:
                    if isinstance(block.content, str):
                        content_text = block.content
                    elif isinstance(block.content, list):
                        parts = []
                        for item in block.content:
                            if hasattr(item, "text"):
                                parts.append(item.text)
                            else:
                                parts.append(str(item))
                        content_text = "\n".join(parts)
                    else:
                        content_text = str(block.content)
                content_text = content_text[:50000]
                char_count = f"{len(content_text):,}" if content_text else "0"
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": tool_name,
                    "summary": f"{tool_name} returned {char_count} chars",
                    "content": content_text,
                })

        # Process local tool_use blocks
        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses and response.stop_reason == "end_turn":
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "ask_human":
                question = tool_use.input["question"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "ask_human",
                    "summary": f"Asking operator: {question[:80]}",
                    "input": {"question": question},
                })
                human_response = await _ask_human(
                    convex_url, deploy_key, scan_id, question,
                )
                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "ask_human",
                    "summary": f"Operator responded",
                    "content": human_response,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Operator response: {human_response}",
                })

            elif tool_use.name == "navigate":
                url = tool_use.input["url"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "navigate",
                    "summary": f"Navigating to {url}",
                    "input": {"url": url},
                })

                try:
                    await stagehand_session.navigate(url=url)
                    title = await pw_page.title()
                    text = await pw_page.inner_text("body")
                    result_text = f"Navigated to {pw_page.url}\nTitle: {title}\n\n{text[:2000]}"
                except Exception as e:
                    result_text = f"Navigation failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "navigate",
                    "summary": f"Loaded {pw_page.url}"[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:5000],
                })

            elif tool_use.name == "act":
                instruction = tool_use.input["instruction"]
                variables = tool_use.input.get("variables")
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "act",
                    "summary": f"Act: {instruction[:100]}",
                    "input": {"instruction": instruction},
                })

                try:
                    kwargs = {"input": instruction}
                    if variables:
                        kwargs["variables"] = variables
                    result = await stagehand_session.act(**kwargs)
                    msg = result.data.result.message if result.data and result.data.result else "Action completed"
                    success = result.data.result.success if result.data and result.data.result else True
                    result_text = f"{'Success' if success else 'Failed'}: {msg}. Now at {pw_page.url}"
                except Exception as e:
                    result_text = f"Act failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "act",
                    "summary": result_text[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "observe":
                instruction = tool_use.input["instruction"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "observe",
                    "summary": f"Observe: {instruction[:100]}",
                    "input": {"instruction": instruction},
                })

                items = []
                try:
                    result = await stagehand_session.observe(instruction=instruction)
                    elements = result.data.result if result.data else []
                    for el in (elements or []):
                        d = el.to_dict(exclude_none=True) if hasattr(el, "to_dict") else str(el)
                        items.append(d)
                    result_text = json.dumps(items[:20], indent=2, default=str)
                except Exception as e:
                    result_text = f"Observe failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "observe",
                    "summary": f"Found {len(items)} elements",
                    "content": result_text[:10000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:10000],
                })

            elif tool_use.name == "extract":
                instruction = tool_use.input["instruction"]
                schema = tool_use.input.get("schema")
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "extract",
                    "summary": f"Extract: {instruction[:100]}",
                    "input": {"instruction": instruction},
                })

                try:
                    kwargs = {"instruction": instruction}
                    if schema:
                        kwargs["schema"] = schema
                    result = await stagehand_session.extract(**kwargs)
                    extracted = result.data.result if result.data else {}
                    result_text = json.dumps(extracted, indent=2, default=str)
                except Exception as e:
                    result_text = f"Extract failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "extract",
                    "summary": f"Extracted {len(result_text):,} chars",
                    "content": result_text[:10000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:10000],
                })

            elif tool_use.name == "get_page_content":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "get_page_content",
                    "summary": f"Reading page content at {pw_page.url}",
                })

                try:
                    content = await pw_page.evaluate("""() => {
                        const result = {
                            url: location.href,
                            title: document.title,
                            forms: [],
                            links: [],
                            inputs: [],
                            meta: [],
                        };
                        document.querySelectorAll('form').forEach((f, i) => {
                            result.forms.push({
                                action: f.action, method: f.method, id: f.id,
                                fields: Array.from(f.querySelectorAll('input,select,textarea')).map(el => ({
                                    tag: el.tagName, type: el.type, name: el.name, id: el.id, placeholder: el.placeholder
                                }))
                            });
                        });
                        Array.from(document.querySelectorAll('a[href]')).slice(0, 50).forEach(a => {
                            result.links.push({href: a.href, text: a.textContent?.trim().slice(0, 60)});
                        });
                        document.querySelectorAll('input:not(form input), textarea:not(form textarea)').forEach(el => {
                            result.inputs.push({tag: el.tagName, type: el.type, name: el.name, id: el.id});
                        });
                        document.querySelectorAll('meta').forEach(m => {
                            if (m.name || m.httpEquiv) result.meta.push({name: m.name, httpEquiv: m.httpEquiv, content: m.content});
                        });
                        return result;
                    }""")
                    html = await pw_page.content()
                    content["html_preview"] = html[:8000]
                    result_text = json.dumps(content, indent=2, default=str)
                except Exception as e:
                    result_text = f"Failed to read page: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "get_page_content",
                    "summary": f"Page content: {len(result_text):,} chars",
                    "content": result_text[:15000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:15000],
                })

            elif tool_use.name == "execute_js":
                script = tool_use.input["script"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "execute_js",
                    "summary": f"JS: {script[:80]}",
                    "input": {"script": script},
                })

                try:
                    result = await pw_page.evaluate(script)
                    result_text = json.dumps(result, indent=2, default=str) if result is not None else "undefined"
                except Exception as e:
                    result_text = f"JS execution failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "execute_js",
                    "summary": f"JS returned {len(str(result_text)):,} chars",
                    "content": result_text[:10000],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:10000],
                })

            elif tool_use.name == "screenshot":
                label = tool_use.input.get("label", "screenshot")
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "screenshot",
                    "summary": f"Capturing: {label}",
                })

                try:
                    screenshot_bytes = await pw_page.screenshot(type="png")
                    storage_id = await _upload_screenshot(
                        convex_url, deploy_key, screenshot_bytes,
                    )
                    await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                        "tool": "screenshot",
                        "summary": f"Captured: {label}",
                        "storageId": storage_id,
                    })
                    result_text = f"Screenshot captured: {label}"
                except Exception as e:
                    await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                        "tool": "screenshot",
                        "summary": f"Screenshot failed: {e}",
                    })
                    result_text = f"Screenshot failed: {e}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "submit_findings":
                findings = tool_use.input.get("findings", [])
                summary = tool_use.input.get("summary", "")
                n = len(findings)

                if n <= 1 and len(summary) > 300:
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        "Findings are under-structured — handing off to report writer for proper breakdown...")
                    await _compile_report(convex_url, deploy_key, scan_id, project_id)
                    return

                await _push_action(convex_url, deploy_key, scan_id, "observation",
                    f"Rem is compiling report — {n} findings identified")
                await _submit_report(
                    convex_url, deploy_key,
                    scan_id, project_id,
                    findings,
                    summary,
                )
                return

        messages.append({"role": "user", "content": tool_results})

    # Agent stopped without calling submit_findings — hand off to report writer
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Scanning complete. Handing off to report writer...")
    await _compile_report(convex_url, deploy_key, scan_id, project_id)
