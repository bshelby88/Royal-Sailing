#!/usr/bin/env python3
"""
Cloud Fleet Orchestrator — replaces Hermes + Antigravity SDK.
Runs on GitHub Actions or any cloud VPS. No laptop required.
Calls OpenRouter directly. Reads/writes Airtable. Creates GitHub issues.
"""
import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
AIRTABLE_PAT = os.environ["AIRTABLE_PAT"]
AIRTABLE_BASE = os.environ.get("AIRTABLE_BASE", "appHjVD4pMobyUyNj")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DEFAULT_MODEL = os.environ.get("FLEET_MODEL", "google/gemini-2.5-flash")
REASONING_MODEL = os.environ.get("FLEET_REASONING_MODEL", "anthropic/claude-sonnet-4-6")
MAX_COST_PER_RUN = float(os.environ.get("MAX_COST_PER_RUN", "0.25"))
RUN_TAG = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")


def call_llm(model, messages, temperature=0.3, max_tokens=4000):
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/bshelby88/Royal-Sailing",
        "X-Title": "Royal Agentic Fleet",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            usage = result.get("usage", {})
            cost = (
                usage.get("prompt_tokens", 0) * 0.000001
                + usage.get("completion_tokens", 0) * 0.000002
            )
            return {
                "content": result["choices"][0]["message"]["content"],
                "model": result.get("model", model),
                "tokens_prompt": usage.get("prompt_tokens", 0),
                "tokens_completion": usage.get("completion_tokens", 0),
                "cost_estimate": round(cost, 6),
            }
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except Exception as e:
        return {"error": str(e)}


def airtable_request(method, endpoint, body=None):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_PAT}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except Exception as e:
        return {"error": str(e)}


def get_tasks(status="Ready"):
    formula = urllib.parse.quote(f"{{Status}}='{status}'")
    result = airtable_request(
        "GET", f"Tasks?filterByFormula={formula}&maxRecords=20"
    )
    return result.get("records", [])


def update_task(record_id, fields):
    return airtable_request("PATCH", f"Tasks/{record_id}", {"fields": fields})


def create_run_log(fields):
    return airtable_request("POST", "Runs", {"records": [{"fields": fields}]})


def get_products():
    result = airtable_request("GET", "Products?maxRecords=50")
    return result.get("records", [])


def github_request(endpoint, method="GET", body=None):
    if not GITHUB_TOKEN:
        return {"error": "No GITHUB_TOKEN set"}
    url = f"https://api.github.com/{endpoint}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except Exception as e:
        return {"error": str(e)}


def create_issue(repo, title, body, labels=None):
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return github_request(f"repos/{repo}/issues", "POST", payload)


AGENTS = {
    "scout": {
        "model": DEFAULT_MODEL,
        "system": (
            "You are the Scout Agent for Royal Agentic Enterprises. "
            "Your job is to scan for revenue opportunities: GitHub bounties, "
            "OSS contribution entry points, freelance leads, and x402 service "
            "traffic signals. Return structured JSON with: opportunity_type, "
            "source, title, value_estimate, url, priority (1-5), next_action. "
            "Be concise. Do not hallucinate URLs."
        ),
    },
    "builder": {
        "model": REASONING_MODEL,
        "system": (
            "You are the Builder Agent for Royal Agentic Enterprises. "
            "Your job is to produce code, PRs, documentation, and GitHub "
            "Package updates. Always include working code with tests. "
            "Return structured JSON with: artifact_type, content, "
            "files_changed, verification_steps."
        ),
    },
    "merchant": {
        "model": DEFAULT_MODEL,
        "system": (
            "You are the Merchant Agent for Royal Agentic Enterprises. "
            "Your job is to monitor crypto payment addresses for incoming "
            "USDC/ETH payments on Base, match them to orders in Airtable, "
            "and update order status. Return structured JSON with: address, "
            "tx_hash, amount_received, token, confirmations, order_id, status."
        ),
    },
    "critic": {
        "model": REASONING_MODEL,
        "system": (
            "You are the Critic Agent for Royal Agentic Enterprises. "
            "Your job is to review outputs from other agents against SOPs. "
            "Reject any output that: contains hallucinated URLs, claims "
            "completion without verification, violates guardrails, or "
            "exposes secrets. Return structured JSON with: approved (boolean), "
            "issues (list), required_changes (list)."
        ),
    },
}


def run_fleet():
    print(f"[{RUN_TAG}] Fleet orchestrator starting...")
    total_cost = 0.0
    results = []

    tasks = get_tasks("Ready")
    print(f"  Found {len(tasks)} ready tasks")

    if not tasks:
        print("  No tasks ready. Creating scout task...")
        airtable_request(
            "POST",
            "Tasks",
            {
                "records": [
                    {
                        "fields": {
                            "Name": f"Scout scan {RUN_TAG}",
                            "Status": "Ready",
                            "Agent": "scout",
                            "Priority": 3,
                            "DoD": "Return 5 revenue opportunities with URLs and value estimates",
                            "Created": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                ]
            },
        )
        tasks = get_tasks("Ready")

    for task in tasks[:10]:
        if total_cost >= MAX_COST_PER_RUN:
            print(f"  Cost cap reached (${total_cost:.4f}). Stopping.")
            break

        fields = task["fields"]
        task_name = fields.get("Name", "unnamed")
        agent_name = fields.get("Agent", "builder")
        agent = AGENTS.get(agent_name, AGENTS["builder"])

        print(f"  Executing: {task_name} (agent={agent_name})")

        user_msg = (
            f"Task: {task_name}\n"
            f"Description: {fields.get('DoD', 'No definition of done')}\n"
            f"Context: {fields.get('Context', 'No additional context')}\n"
            f"Priority: {fields.get('Priority', 3)}\n"
            "Execute this task and return structured JSON output."
        )

        result = call_llm(
            model=agent["model"],
            messages=[
                {"role": "system", "content": agent["system"]},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
        )

        if "error" in result:
            print(f"    ERROR: {result['error']}")
            update_task(
                task["id"],
                {
                    "Status": "Error",
                    "Last Error": result["error"][:500],
                    "Last Run": RUN_TAG,
                },
            )
            results.append(
                {"task": task_name, "status": "error", "error": result["error"]}
            )
            continue

        total_cost += result.get("cost_estimate", 0)
        output = result["content"]

        update_task(
            task["id"],
            {
                "Status": "Review",
                "Output": output[:5000],
                "Last Run": RUN_TAG,
                "Model Used": result.get("model", ""),
                "Cost": result.get("cost_estimate", 0),
            },
        )

        print(f"    Done. Cost: ${result.get('cost_estimate', 0):.6f}")
        results.append(
            {
                "task": task_name,
                "status": "completed",
                "cost": result.get("cost_estimate", 0),
                "tokens": result.get("tokens_prompt", 0)
                + result.get("tokens_completion", 0),
            }
        )

    create_run_log(
        {
            "Run ID": RUN_TAG,
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "Tasks Executed": len(results),
            "Total Cost": total_cost,
            "Results": json.dumps(results)[:5000],
            "Status": "completed" if results else "idle",
        }
    )

    print(
        f"[{RUN_TAG}] Fleet cycle complete. {len(results)} tasks. "
        f"Total cost: ${total_cost:.6f}"
    )
    return results


def check_payments():
    wallet = os.environ.get(
        "FLEET_WALLET", "0x9e6A0CE78Bb2915d0758cc6A1cE8eA77f1B71770"
    )
    rpc_url = os.environ.get("BASE_RPC", "https://mainnet.base.org")

    payload = json.dumps(
        {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
    ).encode()
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            block = json.loads(resp.read().decode())
            block_num = int(block["result"], 16)
            print(f"  Base RPC alive. Block: {block_num}. Wallet: {wallet}")
            return {"status": "alive", "block": block_num, "wallet": wallet}
    except Exception as e:
        print(f"  RPC error: {e}")
        return {"status": "error", "error": str(e)}


def check_fly_services():
    services = [
        "nft-alpha-x402",
        "tradingagents-x402",
        "nanobanana-x402",
        "power-pack-x402",
        "royal-ruby-x402",
        "sentry-forge-x402",
        "suprapack-x402",
        "vault-pro-x402",
    ]
    results = {}
    for svc in services:
        url = f"https://{svc}.fly.dev/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                results[svc] = {"status": "ok", "data": data}
        except Exception as e:
            results[svc] = {"status": "down", "error": str(e)}
    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cycle"

    if mode == "cycle":
        run_fleet()
    elif mode == "payments":
        check_payments()
    elif mode == "health":
        print("=== Base RPC ===")
        rpc = check_payments()
        print(json.dumps(rpc, indent=2))
        print("\n=== Fly Services ===")
        fly = check_fly_services()
        for svc, info in fly.items():
            status = info["status"]
            print(f"  {svc}: {status}")
    else:
        print(f"Unknown mode: {mode}. Use: cycle, payments, health")
