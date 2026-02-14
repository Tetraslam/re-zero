"""Sandbox orchestrator — spins up Modal sandboxes for scan jobs.

Sandboxes write directly to Convex (not back to the server) since
Modal containers can't reach localhost.
"""

import modal

MINUTES = 60

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "jq")
    .pip_install(
        "httpx",
        "anthropic",
        "pydantic",
    )
)

app = modal.App("re-zero-sandbox")


@app.function(
    image=sandbox_image,
    timeout=30 * MINUTES,
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

    await _push_action(convex_url, convex_deploy_key, scan_id, "observation", "Cloning repository...")
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
        f"Cloned {repo_url} — {len(file_list)} files"
    )

    if agent == "opus":
        await _run_claude_agent(
            scan_id, project_id, repo_url, work_dir, file_list,
            convex_url, convex_deploy_key,
        )
    else:
        await _run_opencode_agent(
            scan_id, agent, convex_url, convex_deploy_key,
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


async def _submit_report(
    convex_url: str, deploy_key: str,
    scan_id: str, project_id: str, findings: list, summary: str,
):
    """Submit report and mark scan completed directly in Convex."""
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
    """Run security scan using Claude API (Opus 4.6)."""
    import anthropic
    import os
    import subprocess

    client = anthropic.Anthropic()

    system_prompt = f"""You are a security researcher performing a vulnerability audit on a codebase.

Repository: {repo_url}
Working directory: {work_dir}

Your task:
1. Analyze the codebase for security vulnerabilities
2. Focus on: injection flaws, authentication issues, data exposure, misconfigurations, dependency vulnerabilities
3. For each finding, provide: title, severity (critical/high/medium/low/info), description, file location, remediation

Be thorough but precise. Only report real vulnerabilities, not style issues.

Files in repository:
{chr(10).join(file_list[:100])}
"""

    await _push_action(convex_url, deploy_key, scan_id, "reasoning", "Starting security analysis with Opus 4.6...")

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
                                "location": {"type": "string"},
                                "recommendation": {"type": "string"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                    },
                },
                "required": ["summary", "findings"],
            },
        },
    ]

    for turn in range(20):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Always push text/reasoning blocks — they appear alongside tool uses too
        text_blocks = [b.text for b in assistant_content if hasattr(b, "text") and b.type == "text"]
        for text in text_blocks:
            if text.strip():
                await _push_action(convex_url, deploy_key, scan_id, "reasoning", text.strip())

        tool_uses = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_uses:
            break

        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "read_file":
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
                n = len(tool_use.input.get("findings", []))
                await _push_action(convex_url, deploy_key, scan_id, "observation", f"Submitting report with {n} findings...")
                await _submit_report(
                    convex_url, deploy_key,
                    scan_id, project_id,
                    tool_use.input["findings"],
                    tool_use.input["summary"],
                )
                return

        messages.append({"role": "user", "content": tool_results})

    # If we exhausted turns without a submit_findings call, mark failed
    await _push_action(convex_url, deploy_key, scan_id, "observation", "Reached max turns without structured report.")
    await _convex_mutation(convex_url, deploy_key, "scans:updateStatus", {
        "scanId": scan_id,
        "status": "failed",
        "error": "Agent did not submit a structured report within 20 turns.",
    })


async def _run_opencode_agent(
    scan_id: str,
    agent: str,
    convex_url: str,
    deploy_key: str,
):
    """Run security scan using OpenCode SDK with RL-trained models."""
    await _push_action(
        convex_url, deploy_key, scan_id, "observation",
        f"OpenCode SDK agent ({agent}) not yet implemented. Mouad's models need to be deployed first."
    )
