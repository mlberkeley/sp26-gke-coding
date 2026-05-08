"""Iron-curtain static analysis on candidate fix code.

Rejects code that imports forbidden modules, calls forbidden builtins, or
accesses dangerous dunder attributes by name.  Runs on every fixer output
before the candidate is admitted to the gVisor sandbox — defense-in-depth, not
a substitute for sandbox isolation.

Design principles:

- AST-based, not substring matching.  `"cu" + "rl"`, escape tricks, and string
  rebuilds cannot evade an AST walk.
- Allowlist for imports (only known-safe modules), denylist for builtins and
  dunder attributes.  The buggy-script context never legitimately needs file
  I/O, network, subprocess, reflection, or dynamic execution.
- Multiple violations are all reported, not just the first, so reviewers see
  the full picture.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "math",
        "random",
        "re",
        "string",
        "decimal",
        "fractions",
        "statistics",
        "itertools",
        "functools",
        "collections",
        "typing",
        "dataclasses",
        "enum",
        "copy",
        "operator",
        "abc",
        "numbers",
        "heapq",
        "bisect",
    }
)

FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "http",
        "ftplib",
        "smtplib",
        "telnetlib",
        "ctypes",
        "cffi",
        "multiprocessing",
        "threading",
        "signal",
        "pty",
        "commands",
        "pickle",
        "marshal",
        "shelve",
        "dbm",
        "importlib",
        "builtins",
        "pathlib",
        "io",
        "tempfile",
        "shutil",
        "glob",
        "fileinput",
        "asyncio",
        "concurrent",
    }
)

FORBIDDEN_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "breakpoint",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
    }
)

FORBIDDEN_DUNDERS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
        "__dict__",
        "__mro__",
        "__init_subclass__",
        "__import__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
    }
)

_REFLECTIVE_BUILTINS: frozenset[str] = frozenset(
    {"getattr", "setattr", "delattr", "hasattr"}
)


@dataclass(frozen=True)
class Violation:
    line: int
    col: int
    rule: str
    detail: str


def _root_module(name: str) -> str:
    return name.split(".", 1)[0]


def check(code: str) -> list[Violation]:
    """Return policy violations in `code`.  Empty list = approved."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [
            Violation(
                line=exc.lineno or 0,
                col=exc.offset or 0,
                rule="syntax_error",
                detail=str(exc),
            )
        ]

    violations: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_module(alias.name)
                if root in FORBIDDEN_IMPORTS:
                    violations.append(
                        Violation(
                            node.lineno,
                            node.col_offset,
                            "forbidden_import",
                            f"import {alias.name}",
                        )
                    )
                elif root not in ALLOWED_IMPORTS:
                    violations.append(
                        Violation(
                            node.lineno,
                            node.col_offset,
                            "import_not_allowlisted",
                            f"import {alias.name}",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "relative_import",
                        f"from {'.' * node.level}{node.module or ''} import ...",
                    )
                )
                continue
            module = node.module or ""
            root = _root_module(module)
            if root in FORBIDDEN_IMPORTS:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "forbidden_import",
                        f"from {module} import ...",
                    )
                )
            elif root and root not in ALLOWED_IMPORTS:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "import_not_allowlisted",
                        f"from {module} import ...",
                    )
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_BUILTINS:
                    violations.append(
                        Violation(
                            node.lineno,
                            node.col_offset,
                            "forbidden_builtin",
                            f"{node.func.id}(...)",
                        )
                    )
                if (
                    node.func.id in _REFLECTIVE_BUILTINS
                    and len(node.args) >= 2
                ):
                    attr_arg = node.args[1]
                    if not isinstance(attr_arg, ast.Constant):
                        violations.append(
                            Violation(
                                node.lineno,
                                node.col_offset,
                                "reflective_attr_access",
                                f"{node.func.id} with non-literal attribute name",
                            )
                        )
                    elif (
                        isinstance(attr_arg.value, str)
                        and attr_arg.value in FORBIDDEN_DUNDERS
                    ):
                        violations.append(
                            Violation(
                                node.lineno,
                                node.col_offset,
                                "forbidden_dunder_via_getattr",
                                f'{node.func.id}(..., "{attr_arg.value}")',
                            )
                        )
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_DUNDERS:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "forbidden_dunder",
                        f".{node.attr}",
                    )
                )
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_DUNDERS:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "forbidden_dunder_name",
                        node.id,
                    )
                )
            elif node.id in FORBIDDEN_BUILTINS:
                violations.append(
                    Violation(
                        node.lineno,
                        node.col_offset,
                        "forbidden_builtin_ref",
                        node.id,
                    )
                )

    return violations


def is_approved(code: str) -> tuple[bool, list[Violation]]:
    """Return (approved, violations).  approved=True iff the list is empty."""
    violations = check(code)
    return len(violations) == 0, violations


def format_violations(violations: list[Violation]) -> str:
    if not violations:
        return ""
    lines = [f"Iron-curtain policy: {len(violations)} violation(s)"]
    for v in violations:
        lines.append(f"  line {v.line}:{v.col}  [{v.rule}]  {v.detail}")
    return "\n".join(lines)
