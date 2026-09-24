#!/usr/bin/env python3
"""PostToolUse hook: syntax-check any .py file written or edited by Claude."""

import ast
import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path.endswith(".py"):
        return 0

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError:
        return 0

    try:
        ast.parse(source, filename=file_path)
    except SyntaxError as e:
        print(f"Syntax error in {file_path}:{e.lineno}: {e.msg}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
