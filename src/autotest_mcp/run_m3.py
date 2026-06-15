"""M3 知识库 CLI：检索 / 列出已沉淀案例。

  python -m autotest_mcp.run_m3 --kb config/kb.json search "按键 panic"
  python -m autotest_mcp.run_m3 --kb config/kb.json show
"""
from __future__ import annotations

import argparse
import sys

from .knowledge.recall import format_case
from .knowledge.store import FileKnowledgeStore


def main() -> None:
    ap = argparse.ArgumentParser(description="M3 知识库检索")
    ap.add_argument("--kb", default="config/kb.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="列出全部案例")
    s = sub.add_parser("search", help="语义/关键词检索")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    args = ap.parse_args()

    store = FileKnowledgeStore(args.kb)
    if args.cmd == "show":
        cases = store.all()
    else:
        cases = store.search(args.query, k=args.k)

    if not cases:
        print("(空)")
        return
    for c in cases:
        print(format_case(c))
        print()


if __name__ == "__main__":
    sys.exit(main())
