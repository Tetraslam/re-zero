"""Sandbox orchestrator — spins up Modal sandboxes for scan jobs.

Sandboxes write directly to Convex (not back to the server) since
Modal containers can't reach localhost.
"""

import modal
import os

MINUTES = 60


def _get_anthropic_client():
    """Create Anthropic client — uses Bedrock if USE_BEDROCK=true, else direct API."""
    if os.environ.get("USE_BEDROCK") == "true":
        from anthropic import AnthropicBedrock
        return AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
    from anthropic import Anthropic
    return Anthropic()


def _get_model_id(model_name: str) -> str:
    """Map model names to Bedrock model IDs when using Bedrock."""
    if os.environ.get("USE_BEDROCK") != "true":
        return model_name
    mapping = {
        "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
        "claude-sonnet-4-5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "claude-haiku-4-5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
    return mapping.get(model_name, model_name)


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
    )
    .run_commands("playwright install --with-deps chromium")
)

# OpenCode images — for GLM-4.6V and Nemotron via OpenCode SDK
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
    .pip_install("playwright", "aiohttp")
    .run_commands("playwright install --with-deps chromium")
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
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run an OSS security scan in a Modal sandbox."""
    import subprocess

    work_dir = "/root/target"

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

    await _push_action(
        convex_url, convex_deploy_key, scan_id, "observation",
        f"Rem cloned {repo_url} — {len(file_list)} files indexed"
    )

    if agent == "opus":
        await _run_claude_agent(
            scan_id, project_id, repo_url, work_dir, file_list,
            convex_url, convex_deploy_key,
        )
    else:
        await _run_opencode_agent(
            scan_id, project_id, agent, work_dir, file_list,
            repo_url, convex_url, convex_deploy_key,
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
        model=_get_model_id("claude-opus-4-6"),
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
):
    """Run security scan using Claude API (Opus 4.6 or equivalent via Bedrock)."""
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
                model=_get_model_id("claude-opus-4-6"),
                max_tokens=4096,
                system=system_cached,
                tools=tools,
                messages=messages,
            )
        else:
            for attempt in range(3):
                try:
                    response = client.beta.messages.create(
                        model="claude-opus-4-6",
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

# Agent display names for trace messages
_OPENCODE_AGENT_NAMES = {
    "glm": "GLM-4.6V",
    "nemotron": "Nemotron",
}

def _build_opencode_config(agent: str) -> dict:
    """Build opencode.json config for the given agent."""
    import os

    if agent == "glm":
        # OpenRouter is built-in but glm-4.6v isn't in OpenCode's catalog —
        # must register it explicitly under provider.models
        return {
            "provider": {
                "openrouter": {
                    "models": {
                        "z-ai/glm-4.6v": {
                            "name": "GLM-4.6V",
                            "limit": {
                                "context": 131072,
                                "output": 8192,
                            },
                        },
                    },
                },
            },
            "model": "openrouter/z-ai/glm-4.6v",
        }
    elif agent == "nemotron":
        endpoint = os.environ.get("NEMOTRON_ENDPOINT_URL", "")
        return {
            "provider": {
                "nemotron": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Nemotron",
                    "options": {
                        "baseURL": f"{endpoint}/v1" if endpoint else "http://localhost:8000/v1",
                        "apiKey": os.environ.get("NEMOTRON_API_KEY", "dummy"),
                    },
                    "models": {
                        "nemotron-14b-ctf": {
                            "name": "Nemotron-14B CTF",
                            "limit": {
                                "context": 131072,
                                "output": 8192,
                            },
                        },
                    },
                },
            },
            "model": "nemotron/nemotron-14b-ctf",
        }
    else:
        raise ValueError(f"Unknown OpenCode agent: {agent}")


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
    "get_page_content": _make_bridge_tool(
        "get_page_content",
        "Get the current page's HTML, links, forms, and interactive elements. Use this to understand page structure before interacting.",
        "",
    ),
    "click": _make_bridge_tool(
        "click",
        "Click an element by CSS selector or text. Use get_page_content first to find selectors.",
        'selector: tool.schema.string().describe("CSS selector or text: prefix for text content")',
    ),
    "fill_field": _make_bridge_tool(
        "fill_field",
        "Fill a form field with a value. Triggers proper input events.",
        'selector: tool.schema.string().describe("CSS selector for the input"), value: tool.schema.string().describe("Value to fill in")',
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
    """
    import json
    import httpx

    report_submitted = False
    seen_tool_calls = set()  # Track tool call IDs to avoid duplicate push
    seen_text_parts = set()  # Track text/reasoning part IDs already pushed

    try:
        async with client.stream(
            "GET", "/event",
            timeout=httpx.Timeout(None, connect=30),
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                raw = line[5:].strip()
                if not raw:
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")

                # --- Complete part (text, reasoning, tool) ---
                if event_type == "message.part.updated":
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
                    break

                elif event_type == "session.error":
                    error_msg = data.get("properties", {}).get("error", str(data))
                    await _push_action(convex_url, deploy_key, scan_id, "observation",
                        f"Rem encountered an error: {str(error_msg)[:300]}")
                    break

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
    agent: str,
    work_dir: str,
    file_list: list[str],
    repo_url: str,
    convex_url: str,
    deploy_key: str,
):
    """Run security scan using OpenCode SDK with GLM-4.6V or Nemotron."""
    import asyncio
    import json
    import os
    import subprocess
    import httpx
    import traceback

    agent_name = _OPENCODE_AGENT_NAMES.get(agent, agent)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        f"Rem ({agent_name}) initializing OpenCode environment...")

    # 1. Write opencode.json with provider config
    config = _build_opencode_config(agent)
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
        f"Starting OpenCode server with {agent_name}...")

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
            f"OpenCode server ready — {agent_name} agent active")

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
                f"Rem ({agent_name}) starting security analysis...")

            await client.post(
                f"/session/{session_id}/prompt_async",
                json={
                    "system": system_prompt,
                    "parts": [{"type": "text", "text": user_msg}],
                },
                timeout=httpx.Timeout(30, connect=10),
            )

            # Wait for SSE stream to finish (session.idle or error)
            await sse_task

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
# Playwright bridge HTTP server (for OpenCode web scanning)
# ---------------------------------------------------------------------------

async def _run_playwright_bridge(page, convex_url: str, deploy_key: str, scan_id: str, port: int = 4097):
    """Start an HTTP server exposing Playwright operations for OpenCode tools.

    Custom TypeScript tools call fetch("http://localhost:4097/<action>") to
    interact with the browser. Returns the aiohttp server runner for cleanup.
    """
    from aiohttp import web
    import json

    async def handle_navigate(request):
        data = await request.json()
        url = data.get("url", "")
        try:
            resp = await page.goto(url, timeout=15000)
            status = resp.status if resp else "?"
            title = await page.title()
            text = await page.inner_text("body")
            return web.Response(text=f"Navigated to {page.url} (HTTP {status})\nTitle: {title}\n\n{text[:2000]}")
        except Exception as e:
            return web.Response(text=f"Navigation failed: {e}", status=500)

    async def handle_get_page_content(request):
        try:
            content = await page.evaluate("""() => {
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
            html = await page.content()
            content["html_preview"] = html[:8000]
            return web.Response(text=json.dumps(content, indent=2, default=str),
                                content_type="application/json")
        except Exception as e:
            return web.Response(text=f"Failed to read page: {e}", status=500)

    async def handle_click(request):
        data = await request.json()
        selector = data.get("selector", "")
        try:
            if selector.startswith("text:"):
                await page.get_by_text(selector[5:]).first.click(timeout=5000)
            else:
                await page.click(selector, timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            return web.Response(text=f"Clicked {selector}. Now at {page.url}")
        except Exception as e:
            return web.Response(text=f"Click failed: {e}", status=500)

    async def handle_fill_field(request):
        data = await request.json()
        selector = data.get("selector", "")
        value = data.get("value", "")
        try:
            await page.fill(selector, value, timeout=5000)
            return web.Response(text=f"Filled {selector} with value")
        except Exception as e:
            return web.Response(text=f"Fill failed: {e}", status=500)

    async def handle_execute_js(request):
        data = await request.json()
        script = data.get("script", "")
        try:
            result = await page.evaluate(script)
            return web.Response(text=json.dumps(result, indent=2, default=str) if result is not None else "undefined")
        except Exception as e:
            return web.Response(text=f"JS execution failed: {e}", status=500)

    async def handle_screenshot(request):
        data = await request.json()
        label = data.get("label", "screenshot")
        try:
            screenshot_bytes = await page.screenshot(type="png")
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
    app.router.add_post("/get_page_content", handle_get_page_content)
    app.router.add_post("/click", handle_click)
    app.router.add_post("/fill_field", handle_fill_field)
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
    agent: str,
    target_url: str,
    test_account: dict | None,
    user_context: str | None,
    page,
    work_dir: str,
    convex_url: str,
    deploy_key: str,
):
    """Run web pentesting using OpenCode SDK with GLM-4.6V + Playwright bridge."""
    import asyncio
    import json
    import os
    import subprocess
    import httpx

    agent_name = _OPENCODE_AGENT_NAMES.get(agent, agent)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        f"Rem ({agent_name}) initializing OpenCode for web scanning...")

    # 1. Start Playwright bridge HTTP server on port 4097
    bridge_runner = await _run_playwright_bridge(page, convex_url, deploy_key, scan_id)
    await _push_action(convex_url, deploy_key, scan_id, "observation",
        "Playwright bridge server active on port 4097")

    try:
        # 2. Write opencode.json with provider config
        config = _build_opencode_config(agent)
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
            f"Starting OpenCode server with {agent_name}...")

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
                f"OpenCode server ready — {agent_name} agent active for web scanning")

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

You have browser tools: navigate, get_page_content, click, fill_field, execute_js, screenshot.

Methodology:
1. Use get_page_content to understand the page structure — forms, links, inputs
2. Check security headers and cookies via execute_js
3. Crawl key pages — forms, login, search, API endpoints, admin paths
4. Actively test for vulnerabilities:
   - XSS: inject payloads via fill_field and navigate to URL params
   - SQL injection: test inputs with ' OR 1=1 --, UNION SELECT, etc.
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
                    f"Rem ({agent_name}) starting web penetration test...")

                await client.post(
                    f"/session/{session_id}/prompt_async",
                    json={
                        "system": system_prompt,
                        "parts": [{"type": "text", "text": user_msg}],
                    },
                    timeout=httpx.Timeout(30, connect=10),
                )

                await sse_task

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
# OpenCode Modal functions (separate images for GLM-4.6V / Nemotron)
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
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run an OSS security scan using OpenCode (GLM-4.6V or Nemotron)."""
    import subprocess

    work_dir = "/root/target"

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

    await _push_action(
        convex_url, convex_deploy_key, scan_id, "observation",
        f"Rem cloned {repo_url} — {len(file_list)} files indexed"
    )

    await _run_opencode_agent(
        scan_id, project_id, agent, work_dir, file_list,
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
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run a web pentesting scan using OpenCode (GLM-4.6V only)."""
    if agent == "nemotron":
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            "Nemotron does not support web scanning (no image input).",
        )
        await _convex_mutation(convex_url, convex_deploy_key, "scans:updateStatus", {
            "scanId": scan_id,
            "status": "failed",
            "error": "Nemotron does not support web scanning.",
        })
        return

    from playwright.async_api import async_playwright

    work_dir = "/root/target"
    import os
    os.makedirs(work_dir, exist_ok=True)

    try:
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            f"Rem ({_OPENCODE_AGENT_NAMES.get(agent, agent)}) launching headless browser targeting {target_url}...",
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(target_url, timeout=20000)

            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Browser active — loaded {page.url}",
            )

            await _run_web_opencode_agent(
                scan_id, project_id, agent, target_url,
                test_account, user_context, page, work_dir,
                convex_url, convex_deploy_key,
            )

            await browser.close()

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
# Web pentesting scan (Playwright + headless Chromium)
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
    agent: str,
    convex_url: str,
    convex_deploy_key: str,
):
    """Run a web application pentesting scan with headless Chromium via Playwright."""
    from playwright.async_api import async_playwright

    try:
        await _push_action(
            convex_url, convex_deploy_key, scan_id, "observation",
            f"Rem is launching a headless browser targeting {target_url}...",
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(target_url, timeout=20000)

            await _push_action(
                convex_url, convex_deploy_key, scan_id, "observation",
                f"Browser active — loaded {page.url}",
            )

            if agent == "opus":
                await _run_web_claude_agent(
                    scan_id, project_id, target_url, test_account,
                    user_context, page, convex_url, convex_deploy_key,
                )
            else:
                await _push_action(
                    convex_url, convex_deploy_key, scan_id, "observation",
                    f"Rem ({agent}) not yet deployed for web scanning.",
                )

            await browser.close()

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
    page,
    convex_url: str,
    deploy_key: str,
):
    """Run web pentesting using Claude Opus 4.6 (or equivalent via Bedrock) with Playwright browser tools."""
    import anthropic
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
You have an ask_human tool. The operator is watching the scan live and can help you. When you hit something you can't get past alone — 2FA codes, email verification, CAPTCHAs, bot detection, or any authentication challenge — use ask_human to request what you need. Don't skip these and move on to unauthenticated testing; the whole point of having test credentials is to test the authenticated surface. Ask, wait for the response, then continue.

Methodology:
1. Use get_page_content to understand the page structure — forms, links, inputs
2. Check security headers and cookies via execute_js
3. Crawl key pages — forms, login, search, API endpoints, admin paths
4. Actively test for vulnerabilities:
   - XSS: inject payloads via fill_field and navigate to URL params
   - SQL injection: test inputs with ' OR 1=1 --, UNION SELECT, etc.
   - Auth bypass: navigate to /admin, /api/users, modify IDs in URLs
   - CSRF: check if forms have anti-CSRF tokens (get_page_content)
   - Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options
   - Cookie flags: HttpOnly, Secure, SameSite
   - Info disclosure: error messages, stack traces, .env, .git, robots.txt
   - CORS: check Access-Control-Allow-Origin via execute_js
   - Directory traversal: try ../../etc/passwd in file parameters
5. Take screenshots of important findings as visual evidence
6. Submit your report with all findings

For click and fill_field, use CSS selectors. Use get_page_content first to find the right selectors.

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
            "name": "get_page_content",
            "description": "Get the current page's HTML, links, forms, and interactive elements. Use this to understand page structure before interacting.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "click",
            "description": "Click an element by CSS selector or text. Use get_page_content first to find selectors.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector (e.g. 'button.login', '#submit', 'a[href=\"/admin\"]') or text: prefix for text content (e.g. 'text:Sign In')"},
                },
                "required": ["selector"],
            },
        },
        {
            "name": "fill_field",
            "description": "Fill a form field with a value. Triggers proper input events.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector for the input field"},
                    "value": {"type": "string", "description": "Value to fill in"},
                },
                "required": ["selector", "value"],
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
                model=_get_model_id("claude-opus-4-6"),
                max_tokens=4096,
                system=system_cached,
                tools=tools,
                messages=messages,
            )
        else:
            for attempt in range(3):
                try:
                    response = client.beta.messages.create(
                        model="claude-opus-4-6",
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
                    resp = await page.goto(url, timeout=15000)
                    status = resp.status if resp else "?"
                    title = await page.title()
                    text = await page.inner_text("body")
                    result_text = f"Navigated to {page.url} (HTTP {status})\nTitle: {title}\n\n{text[:2000]}"
                except Exception as e:
                    result_text = f"Navigation failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "navigate",
                    "summary": f"Loaded {page.url}"[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text[:5000],
                })

            elif tool_use.name == "get_page_content":
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "get_page_content",
                    "summary": f"Reading page content at {page.url}",
                })

                try:
                    # Get a structured view of the page
                    content = await page.evaluate("""() => {
                        const result = {
                            url: location.href,
                            title: document.title,
                            forms: [],
                            links: [],
                            inputs: [],
                            meta: [],
                        };
                        // Forms
                        document.querySelectorAll('form').forEach((f, i) => {
                            result.forms.push({
                                action: f.action, method: f.method, id: f.id,
                                fields: Array.from(f.querySelectorAll('input,select,textarea')).map(el => ({
                                    tag: el.tagName, type: el.type, name: el.name, id: el.id, placeholder: el.placeholder
                                }))
                            });
                        });
                        // Links (first 50)
                        Array.from(document.querySelectorAll('a[href]')).slice(0, 50).forEach(a => {
                            result.links.push({href: a.href, text: a.textContent?.trim().slice(0, 60)});
                        });
                        // Standalone inputs
                        document.querySelectorAll('input:not(form input), textarea:not(form textarea)').forEach(el => {
                            result.inputs.push({tag: el.tagName, type: el.type, name: el.name, id: el.id});
                        });
                        // Meta tags
                        document.querySelectorAll('meta').forEach(m => {
                            if (m.name || m.httpEquiv) result.meta.push({name: m.name, httpEquiv: m.httpEquiv, content: m.content});
                        });
                        return result;
                    }""")
                    # Also get truncated HTML
                    html = await page.content()
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

            elif tool_use.name == "click":
                selector = tool_use.input["selector"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "click",
                    "summary": f"Clicking: {selector[:80]}",
                    "input": {"selector": selector},
                })

                try:
                    if selector.startswith("text:"):
                        await page.get_by_text(selector[5:]).first.click(timeout=5000)
                    else:
                        await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    result_text = f"Clicked {selector}. Now at {page.url}"
                except Exception as e:
                    result_text = f"Click failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "click",
                    "summary": result_text[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "fill_field":
                selector = tool_use.input["selector"]
                value = tool_use.input["value"]
                display_val = value if len(value) < 40 else value[:37] + "..."
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "fill_field",
                    "summary": f"Filling {selector[:40]} with '{display_val}'",
                    "input": {"selector": selector, "value": value},
                })

                try:
                    await page.fill(selector, value, timeout=5000)
                    result_text = f"Filled {selector} with value"
                except Exception as e:
                    result_text = f"Fill failed: {e}"

                await _push_action(convex_url, deploy_key, scan_id, "tool_result", {
                    "tool": "fill_field",
                    "summary": result_text[:120],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                })

            elif tool_use.name == "execute_js":
                script = tool_use.input["script"]
                await _push_action(convex_url, deploy_key, scan_id, "tool_call", {
                    "tool": "execute_js",
                    "summary": f"JS: {script[:80]}",
                    "input": {"script": script},
                })

                try:
                    result = await page.evaluate(script)
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
                    screenshot_bytes = await page.screenshot(type="png")
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
