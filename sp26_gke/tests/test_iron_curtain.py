"""Tests for the iron-curtain static-analysis policy.

Covers known prompt-injection-into-fix bypass classes (denylist evasion,
dynamic exec, reflection, dunder traversal) plus sanity checks that
realistic clean fixes pass.
"""

from sp26_gke.agent.policy import format_violations, is_approved


# ---------------------------------------------------------------------------
# Clean code paths
# ---------------------------------------------------------------------------


def test_pure_compute_passes():
    code = """
def add(a, b):
    return a + b
"""
    approved, violations = is_approved(code)
    assert approved, format_violations(violations)


def test_allowed_import_math_passes():
    code = """
import math

def circle_area(r):
    return math.pi * r * r
"""
    approved, violations = is_approved(code)
    assert approved, format_violations(violations)


def test_realistic_buggy_fibonacci_fix_passes():
    code = """
def fibonacci(n):
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b
"""
    approved, violations = is_approved(code)
    assert approved, format_violations(violations)


def test_realistic_calculator_class_passes():
    code = """
class Calculator:
    def __init__(self):
        self.value = 0

    def add(self, x):
        self.value += x
        return self.value

    def subtract(self, x):
        self.value -= x
        return self.value
"""
    approved, violations = is_approved(code)
    assert approved, format_violations(violations)


def test_getattr_with_string_literal_passes():
    code = "x = getattr(obj, 'method_name')"
    approved, violations = is_approved(code)
    assert approved, format_violations(violations)


# ---------------------------------------------------------------------------
# Direct violations
# ---------------------------------------------------------------------------


def test_subprocess_blocked():
    approved, violations = is_approved("import subprocess\nsubprocess.run(['ls'])")
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_os_system_blocked_via_import():
    approved, violations = is_approved("import os\nos.system('ls')")
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_eval_call_blocked():
    approved, violations = is_approved("x = eval('1+1')")
    assert not approved
    assert any(
        v.rule == "forbidden_builtin" and "eval" in v.detail for v in violations
    )


def test_exec_call_blocked():
    approved, violations = is_approved("exec('x = 1')")
    assert not approved
    assert any(v.rule == "forbidden_builtin" for v in violations)


def test_compile_call_blocked():
    approved, violations = is_approved("compile('x = 1', '', 'exec')")
    assert not approved
    assert any(v.rule == "forbidden_builtin" for v in violations)


def test_open_call_blocked():
    approved, violations = is_approved("open('/etc/passwd')")
    assert not approved
    assert any(v.rule == "forbidden_builtin" for v in violations)


def test_pathlib_blocked():
    code = "from pathlib import Path\nPath('/etc/passwd').read_text()"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_relative_import_blocked():
    approved, violations = is_approved("from . import utils")
    assert not approved
    assert any(v.rule == "relative_import" for v in violations)


def test_unknown_third_party_blocked():
    approved, violations = is_approved("import some_random_package")
    assert not approved
    assert any(v.rule == "import_not_allowlisted" for v in violations)


# ---------------------------------------------------------------------------
# Bypass classes — these are why an AST walk + Name check matter
# ---------------------------------------------------------------------------


def test_dunder_class_subclasses_chain_blocked():
    code = "x = ().__class__.__bases__[0].__subclasses__()"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_dunder" for v in violations)


def test_dunder_import_call_blocked():
    code = "__import__('os').system('ls')"
    approved, violations = is_approved(code)
    assert not approved
    assert any("__import__" in v.detail or v.detail == "__import__" for v in violations)


def test_globals_eval_lookup_blocked():
    code = "x = globals()['eval']('1+1')"
    approved, violations = is_approved(code)
    assert not approved
    # globals() must be flagged even though we never see the literal 'eval'
    assert any("globals" in v.detail for v in violations)


def test_getattr_with_non_literal_blocked():
    code = "x = getattr(obj, attr_name)"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "reflective_attr_access" for v in violations)


def test_getattr_with_concatenated_string_blocked():
    code = "x = getattr(obj, 'pre' + 'fix')"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "reflective_attr_access" for v in violations)


def test_eval_aliased_via_name_blocked():
    """`f = eval; f('...')` — references eval as a Name without calling.

    This is a classic denylist bypass; the Name-check branch catches it.
    """
    code = """
f = eval
f('1 + 1')
"""
    approved, violations = is_approved(code)
    assert not approved
    assert any(
        v.rule == "forbidden_builtin_ref" and v.detail == "eval" for v in violations
    )


def test_open_aliased_blocked():
    code = "f = open"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_builtin_ref" for v in violations)


def test_local_import_inside_function_blocked():
    code = """
def trojan():
    import os
    os.system('rm -rf /')
"""
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_local_import_inside_class_blocked():
    code = """
class Foo:
    def method(self):
        import socket
        return socket.gethostname()
"""
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_dunder_dict_access_blocked():
    code = "x = obj.__dict__['secret']"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_dunder" for v in violations)


def test_builtins_attribute_access_blocked():
    code = "x = some_obj.__builtins__"
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_dunder" for v in violations)


def test_async_function_imports_blocked():
    code = """
async def fetch():
    import urllib.request
    return urllib.request.urlopen('http://evil')
"""
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_import" for v in violations)


def test_decorator_referencing_eval_blocked():
    code = """
@eval
def f():
    pass
"""
    approved, violations = is_approved(code)
    assert not approved
    assert any(v.rule == "forbidden_builtin_ref" for v in violations)


def test_multiple_violations_all_reported():
    code = """
import os
import socket
x = eval('1')
y = open('/etc/passwd')
"""
    _, violations = is_approved(code)
    rules = {v.rule for v in violations}
    assert "forbidden_import" in rules
    assert "forbidden_builtin" in rules
    assert len(violations) >= 4


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_syntax_error_reported_as_violation():
    approved, violations = is_approved("def broken(")
    assert not approved
    assert any(v.rule == "syntax_error" for v in violations)


def test_empty_code_passes():
    approved, _ = is_approved("")
    assert approved


def test_format_violations_renders_lines():
    _, violations = is_approved("import os")
    rendered = format_violations(violations)
    assert "Iron-curtain policy" in rendered
    assert "forbidden_import" in rendered
