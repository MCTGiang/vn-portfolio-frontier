"""Pre-commit hook: fail if non-ASCII characters appear in Python/SQL source.

Scope: comments and docstrings in .py files, line comments in .sql files.
String literals (including SQL string literals that may hold Vietnamese data
values) are intentionally exempted.

Usage (invoked by pre-commit):
    python scripts/check_ascii.py <file1> <file2> ...

Exit codes:
    0 - all files pass
    1 - one or more files contain non-ASCII in a comment or docstring
    2 - internal error

CONTRIBUTING.md explains the convention. To re-enable Vietnamese narrative in
a specific case (should be rare), add a `# noqa: ascii` marker on the line.
"""

from __future__ import annotations

import ast
import contextlib
import pathlib
import re
import sys
from collections.abc import Iterator

NON_ASCII = re.compile(r"[^\x00-\x7f]")
NOQA = re.compile(r"#\s*noqa:\s*ascii", re.IGNORECASE)


def _ensure_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8 so non-ASCII snippets can be printed on Windows cp1252."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def _iter_py_offenses(src: str) -> Iterator[tuple[int, str, str]]:
    """Yield (line_number, kind, snippet) for every non-ASCII hit in comments/docstrings."""
    # Pass 1: inline comments
    for lineno, line in enumerate(src.splitlines(), start=1):
        if NOQA.search(line):
            continue
        hash_idx = _find_comment_start(line)
        if hash_idx < 0:
            continue
        comment = line[hash_idx:]
        if NON_ASCII.search(comment):
            yield lineno, "comment", comment.strip()

    # Pass 2: docstrings (via AST so we only hit real docstrings)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and NON_ASCII.search(doc):
                lineno = node.body[0].lineno if node.body else getattr(node, "lineno", 1)
                yield lineno, "docstring", doc.strip().splitlines()[0]


def _find_comment_start(line: str) -> int:
    """Return index of the '#' that starts an inline comment, or -1 if none.

    Skips '#' inside string literals (single, double, triple-quoted).
    """
    i = 0
    n = len(line)
    in_string: str | None = None
    while i < n:
        ch = line[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if line.startswith(in_string, i):
                i += len(in_string)
                in_string = None
                continue
            i += 1
            continue
        # Not inside a string literal
        if ch in ("'", '"'):
            # Detect triple vs single
            triple = ch * 3
            if line.startswith(triple, i):
                in_string = triple
                i += 3
            else:
                in_string = ch
                i += 1
            continue
        if ch == "#":
            return i
        i += 1
    return -1


def _iter_sql_offenses(src: str) -> Iterator[tuple[int, str, str]]:
    """Yield (line_number, kind, snippet) for non-ASCII in SQL line comments."""
    for lineno, line in enumerate(src.splitlines(), start=1):
        if NOQA.search(line):
            continue
        # Find '--' not inside a quoted string
        comment_idx = _find_sql_comment_start(line)
        if comment_idx < 0:
            continue
        comment = line[comment_idx:]
        if NON_ASCII.search(comment):
            yield lineno, "comment", comment.strip()


def _find_sql_comment_start(line: str) -> int:
    """Return index of '--' line comment, or -1 if not present outside strings."""
    i = 0
    n = len(line)
    in_quote: str | None = None
    while i < n:
        ch = line[i]
        if in_quote:
            if ch == in_quote:
                # Handle escaped quote by doubling (SQL convention)
                if i + 1 < n and line[i + 1] == in_quote:
                    i += 2
                    continue
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_quote = ch
            i += 1
            continue
        if ch == "-" and i + 1 < n and line[i + 1] == "-":
            return i
        i += 1
    return -1


def check_file(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """Return a list of offenses for one file (empty if clean)."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{path}: cannot read ({exc})", file=sys.stderr)
        return [(0, "error", str(exc))]
    if path.suffix == ".py":
        return list(_iter_py_offenses(src))
    if path.suffix == ".sql":
        return list(_iter_sql_offenses(src))
    return []


def main(argv: list[str]) -> int:
    _ensure_utf8_streams()
    if not argv:
        return 0
    total = 0
    for arg in argv:
        p = pathlib.Path(arg)
        if not p.exists():
            continue
        offenses = check_file(p)
        if offenses:
            for lineno, kind, snippet in offenses:
                shown = snippet[:120] + ("..." if len(snippet) > 120 else "")
                print(f"{p}:{lineno}: non-ASCII in {kind}: {shown}")
            total += len(offenses)
    if total:
        print(
            f"\ncheck-ascii: {total} offense(s). "
            "Translate to English or add '# noqa: ascii' on the offending line.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
