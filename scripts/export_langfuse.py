#!/usr/bin/env python3
"""Exporte en local les N dernières requêtes `chat-message` de Langfuse, avec toutes les observations.

Lecture seule (CLI `langfuse-cli api observations|scores|comments list`). Les clés viennent de `.env`.
Sortie : data/output/langfuse/ (ignoré par git, contient le texte des prompts : données fictives seulement).

    python3 scripts/export_langfuse.py [--n 200] [--out data/output/langfuse]

Fichiers produits :
  raw/observations_window.json   toutes les observations de la fenêtre de temps (brut, métadonnées complètes)
  raw/scores.json, raw/comments.json
  requests/NNN_<date>_<traceId8>.json   une requête = résumé + toutes ses observations triées
  requests.jsonl / requests.csv         un résumé par requête (la vue d'ensemble pour l'analyse)
  analysis_runs.jsonl                   les traces `analysis-run` de la même fenêtre (autres agents)
  orphans.jsonl                         racines hors requête (kb.retrieve, guardrail.*, invoke_agent …)
  README.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"


def load_env() -> dict:
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        m = re.match(r'\s*([A-Z_]+)\s*=\s*"?([^"\n]*)"?\s*$', line)
        if m and m.group(1).startswith("LANGFUSE_"):
            env[m.group(1)] = m.group(2)
    env["LANGFUSE_HOST"] = env["LANGFUSE_BASE_URL"]
    return env


ENV = load_env()


def cli(*args: str) -> dict:
    out = subprocess.run(
        ["npx", "langfuse-cli", "api", *args, "--json"],
        capture_output=True, text=True, env=ENV, cwd=ROOT, check=True,
    ).stdout
    res = json.loads(out)
    if res["status"] != 200:
        raise RuntimeError(f"HTTP {res['status']} pour {args}: {res['body']}")
    return res["body"]


def jl(v):
    """Parse une chaîne JSON si possible, sinon renvoie la valeur telle quelle."""
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def summarize(root: dict, obs: list[dict]) -> dict:
    inp, out = jl(root.get("input")), jl(root.get("output"))
    inp = inp if isinstance(inp, dict) else {}
    out = out if isinstance(out, dict) else {}
    status = root.get("statusMessage") or ""
    m = re.match(r"ApiError: ([A-Z_]+): ?(.*)", status, re.S)
    guards = []
    for o in obs:
        if o["type"] == "GUARDRAIL":
            g = jl(o.get("output"))
            gi = jl(o.get("input"))
            guards.append({
                "name": o["name"], "blocked": (g or {}).get("blocked") if isinstance(g, dict) else None,
                "checked": (g or {}).get("checked") if isinstance(g, dict) else None,
                "textLength": (gi or {}).get("textLength") if isinstance(gi, dict) else None,
                "level": o["level"], "statusMessage": o.get("statusMessage") or "", "latency": o.get("latency"),
            })
    tools = []
    for o in obs:
        md = o.get("metadata") or {}
        if "attributes.gen_ai.tool.status" in md or md.get("attributes.gen_ai.operation.name") == "execute_tool":
            tools.append({
                "name": o["name"], "status": md.get("attributes.gen_ai.tool.status"), "level": o["level"],
                "statusMessage": o.get("statusMessage") or "", "latency": o.get("latency"),
                "startTime": o["startTime"],
            })
    tools.sort(key=lambda t: t["startTime"])
    agents = sorted({o["name"].removeprefix("invoke_agent ") for o in obs if o["name"].startswith("invoke_agent ")})
    llm = [o for o in obs if o.get("model")]
    usage: dict[str, float] = defaultdict(float)
    for o in obs:
        for k, v in (o.get("usageDetails") or {}).items():
            if isinstance(v, (int, float)):
                usage[k] += v
    md = root.get("metadata") or {}
    return {
        "traceId": root["traceId"], "startTime": root["startTime"], "endTime": root.get("endTime"),
        "latency_s": root.get("latency"), "sessionId": root.get("sessionId") or None,
        "userId": root.get("userId") or None, "tags": root.get("tags"),
        "level": root["level"], "statusMessage": status,
        "error_code": m.group(1) if m else None, "error_text": m.group(2) if m else None,
        "user_message": inp.get("content"), "knownUserLanguage": inp.get("knownUserLanguage"),
        "user_message_chars": len(inp.get("content") or ""),
        "reply": out.get("reply"), "userLanguage": out.get("userLanguage"),
        "hasMandateDraft": out.get("hasMandateDraft"), "quickRepliesCount": out.get("quickRepliesCount"),
        "root_output_other": {k: v for k, v in out.items() if k not in
                              ("reply", "userLanguage", "hasMandateDraft", "quickRepliesCount")} or None,
        "guardrails": guards,
        "guardrail_input_blocked": any(g["blocked"] for g in guards if g["name"] == "guardrail.input"),
        "guardrail_output_blocked": any(g["blocked"] for g in guards if g["name"] == "guardrail.output"),
        "agents_invoked": agents, "tools": tools,
        "tools_failed": [t["name"] for t in tools if t["level"] == "ERROR" or (t["status"] not in (None, "success"))],
        "llm_calls": len(llm), "models": sorted({o["model"] for o in llm}),
        "usage_totals": dict(usage), "total_cost": sum(o.get("totalCost") or 0 for o in obs),
        "observation_count": len(obs),
        "error_observations": [{"name": o["name"], "type": o["type"], "statusMessage": o.get("statusMessage")}
                               for o in obs if o["level"] == "ERROR" and o is not root],
        "service_version": md.get("resourceAttributes.service.version"),
        "service_instance": md.get("resourceAttributes.service.instance.id"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default="data/output/langfuse")
    a = ap.parse_args()
    out = ROOT / a.out
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "requests").mkdir(exist_ok=True)

    roots = cli("observations", "list", "--is-root-observation", "--name", "chat-message",
                "--fields", "core,basic", "--limit", "500", "--all", "--max-items", "5000")["data"]
    roots.sort(key=lambda r: r["startTime"], reverse=True)
    chosen = roots[: a.n]
    t0 = chosen[-1]["startTime"]
    print(f"{len(chosen)} requêtes chat-message, de {t0} à {chosen[0]['startTime']}", file=sys.stderr)

    base = ["observations", "list", "--from-start-time", t0,"--fields", FIELDS,
            "--limit", "500", "--all", "--max-items", "500000"]
    first = cli(*base)["data"]
    keys = sorted({k for o in first for k in (o.get("metadata") or {})})
    body = cli(*base, "--expand-metadata", ",".join(keys))
    allobs = body["data"]
    (out / "raw" / "observations_window.json").write_text(json.dumps(allobs, ensure_ascii=False, indent=1))
    for name in ("scores", "comments"):
        (out / "raw" / f"{name}.json").write_text(
            json.dumps(cli(name, "list", "--all", "--max-items", "50000"), ensure_ascii=False, indent=1))

    by_trace: dict[str, list] = defaultdict(list)
    for o in allobs:
        by_trace[o["traceId"]].append(o)
    for v in by_trace.values():
        v.sort(key=lambda o: (o["startTime"], o["endTime"] or ""))

    chosen.sort(key=lambda r: r["startTime"])
    sess_idx: dict[str, int] = defaultdict(int)
    summaries = []
    for i, r in enumerate(chosen, 1):
        obs = by_trace[r["traceId"]]
        root = next(o for o in obs if o["id"] == r["id"])
        s = summarize(root, obs)
        if s["sessionId"]:
            sess_idx[s["sessionId"]] += 1
            s["turn_in_session"] = sess_idx[s["sessionId"]]
        s["rank_oldest_first"] = i
        summaries.append(s)
        fn = f"{i:03d}_{root['startTime'][:19].replace(':', '-')}_{root['traceId'][:8]}.json"
        (out / "requests" / fn).write_text(json.dumps({"summary": s, "observations": obs}, ensure_ascii=False, indent=1))
        s["file"] = f"requests/{fn}"

    with (out / "requests.jsonl").open("w") as f:
        for s in summaries:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    flat = ["rank_oldest_first", "startTime", "latency_s", "sessionId", "turn_in_session", "level", "error_code",
            "guardrail_input_blocked", "guardrail_output_blocked", "user_message_chars", "userLanguage",
            "llm_calls", "total_cost", "service_version", "traceId", "user_message", "error_text", "reply", "file"]
    with (out / "requests.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(flat)
        for s in summaries:
            w.writerow([s.get(k) for k in flat])

    chosen_traces = {s["traceId"] for s in summaries}
    runs, orphans = [], []
    for t, obs in by_trace.items():
        if t in chosen_traces:
            continue
        for o in obs:
            if o["parentObservationId"] is None:
                rec = {"summary": summarize(o, obs) if o["name"] == "analysis-run" else None, "root": o,
                       "observations": obs if o["name"] == "analysis-run" else None}
                (runs if o["name"] == "analysis-run" else orphans).append(rec)
    with (out / "analysis_runs.jsonl").open("w") as f:
        for r in sorted(runs, key=lambda r: r["root"]["startTime"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out / "orphans.jsonl").open("w") as f:
        for r in sorted(orphans, key=lambda r: r["root"]["startTime"]):
            f.write(json.dumps(r["root"], ensure_ascii=False) + "\n")
    print(f"{len(summaries)} requêtes, {len(allobs)} observations, {len(runs)} analysis-run, "
          f"{len(orphans)} racines orphelines → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
