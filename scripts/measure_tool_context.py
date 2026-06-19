#!/usr/bin/env python3
"""Measure the token cost of the MCP tool surface — "context burned on load".

An MCP client hands the model every tool's wire definition (name + description
+ input_schema) plus the server ``instructions`` *once per session*, before any
work happens. That payload is the context this server spends just by being
connected. This script reconstructs that payload from the live server and
counts its tokens with a local llama.cpp vocab via ``llama-tokenize`` —
deterministic and offline.

The absolute number is a proxy (Llama-3 BPE, not Claude's tokenizer); the point
is the *delta* across a fix. Use one vocab consistently and compare snapshots.

    python scripts/measure_tool_context.py                 # human report
    python scripts/measure_tool_context.py --save baseline # snapshot to measure/baseline.json
    python scripts/measure_tool_context.py --compare baseline   # delta vs a snapshot
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LLAMA_TOKENIZE = os.environ.get(
    "LLAMA_TOKENIZE", "/home/kyle/code/llama.cpp/build/bin/llama-tokenize"
)
VOCAB = os.environ.get(
    "LLAMA_VOCAB", "/home/kyle/code/llama.cpp/models/ggml-vocab-llama-bpe.gguf"
)
SNAP_DIR = Path(__file__).resolve().parent.parent / "measure"


def count_tokens(text: str) -> int:
    """Exact token count of ``text`` under the configured llama.cpp vocab."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        out = subprocess.run(
            [LLAMA_TOKENIZE, "-m", VOCAB, "-f", path,
             "--ids", "--no-bos", "--no-escape", "--log-disable"],
            capture_output=True, text=True, check=True,
        ).stdout
    finally:
        os.unlink(path)
    return len(json.loads(out))


def collect() -> tuple[str, list[dict]]:
    """Return (instructions, [{module, name, wire}]) from the live server."""
    from defernowork_mcp import server as srv

    srv._http_transport_mode = False
    mcp = srv.create_server()
    tm = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    tools = getattr(tm, "_tools", None) or getattr(tm, "tools", None)

    rows = []
    for name in sorted(tools):
        t = tools[name]
        fn = getattr(t, "fn", None)
        module = getattr(fn, "__module__", "?").rsplit(".", 1)[-1]
        wire = {
            "name": t.name,
            "description": t.description or "",
            "input_schema": getattr(t, "parameters", {}) or {},
        }
        rows.append({"module": module, "name": name, "wire": wire})
    return mcp.instructions or "", rows


def measure() -> dict:
    instructions, rows = collect()
    # The whole payload as a client would serialize it, in one tokenize pass —
    # the headline "load cost".
    payload = json.dumps(
        {"instructions": instructions, "tools": [r["wire"] for r in rows]},
        ensure_ascii=False,
    )
    total = count_tokens(payload)
    instr_tokens = count_tokens(instructions)
    per_tool = {
        r["name"]: {
            "module": r["module"],
            "tokens": count_tokens(json.dumps(r["wire"], ensure_ascii=False)),
        }
        for r in rows
    }
    return {
        "vocab": Path(VOCAB).name,
        "tool_count": len(rows),
        "total_tokens": total,
        "instructions_tokens": instr_tokens,
        "per_tool": per_tool,
    }


def _module_subtotals(snap: dict) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for name, info in snap["per_tool"].items():
        m = agg.setdefault(info["module"], {"tokens": 0, "count": 0})
        m["tokens"] += info["tokens"]
        m["count"] += 1
    return agg


def report(snap: dict) -> None:
    print(f"vocab={snap['vocab']}  tools={snap['tool_count']}  "
          f"TOTAL={snap['total_tokens']} tok  (instructions={snap['instructions_tokens']})")
    print("\nby module (sum of per-tool wire tokens):")
    for mod, agg in sorted(_module_subtotals(snap).items(),
                           key=lambda kv: -kv[1]["tokens"]):
        print(f"  {agg['tokens']:6d}  {agg['count']:3d}  {mod}")
    print("\ntop 15 tools:")
    for name, info in sorted(snap["per_tool"].items(),
                             key=lambda kv: -kv[1]["tokens"])[:15]:
        print(f"  {info['tokens']:5d}  {name}  ({info['module']})")


def compare(snap: dict, base: dict) -> None:
    d = snap["total_tokens"] - base["total_tokens"]
    print(f"\nTOTAL {base['total_tokens']} -> {snap['total_tokens']}  "
          f"({d:+d} tok, {100*d/base['total_tokens']:+.1f}%)   "
          f"tools {base['tool_count']} -> {snap['tool_count']}")
    base_tools, now_tools = set(base["per_tool"]), set(snap["per_tool"])
    for n in sorted(base_tools - now_tools):
        print(f"  removed  -{base['per_tool'][n]['tokens']:5d}  {n}")
    for n in sorted(now_tools - base_tools):
        print(f"  added    +{snap['per_tool'][n]['tokens']:5d}  {n}")
    for n in sorted(base_tools & now_tools):
        delta = snap["per_tool"][n]["tokens"] - base["per_tool"][n]["tokens"]
        if delta:
            print(f"  changed  {delta:+5d}  {n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", metavar="NAME", help="write snapshot to measure/<NAME>.json")
    ap.add_argument("--compare", metavar="NAME", help="diff against measure/<NAME>.json")
    ap.add_argument("--json", action="store_true", help="emit raw snapshot JSON")
    args = ap.parse_args()

    snap = measure()
    if args.json:
        print(json.dumps(snap, indent=2))
        return
    report(snap)
    if args.compare:
        base = json.loads((SNAP_DIR / f"{args.compare}.json").read_text())
        compare(snap, base)
    if args.save:
        SNAP_DIR.mkdir(exist_ok=True)
        (SNAP_DIR / f"{args.save}.json").write_text(json.dumps(snap, indent=2))
        print(f"\nsaved measure/{args.save}.json")


if __name__ == "__main__":
    sys.exit(main())
