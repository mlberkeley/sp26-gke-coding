"""
Test suite for buggy_script.py.

Imports each known function/class and tests whichever are present.
Works with: buggy_add, buggy_fibonacci, buggy_binary_search,
            buggy_calculator, buggy_palindrome examples.
"""

import os
import random
import socket
import subprocess
import sys

sys.path.append("/tests")

# -- conditional imports -------------------------------------------------------

try:
    from buggy_script import add  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    add = None

try:
    from buggy_script import fibonacci  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    fibonacci = None
try:
    from buggy_script import (
        binary_search,  # type: ignore[import-not-found,unused-ignore]
    )
except ImportError:
    binary_search = None
try:
    from buggy_script import Calculator  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    Calculator = None
try:
    from buggy_script import (
        is_palindrome,  # type: ignore[import-not-found,unused-ignore]
    )
except ImportError:
    is_palindrome = None

# -- functional tests ----------------------------------------------------------


def test_add():
    if add is None:
        print("SKIP: add not defined")
        return
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
    assert add(10**6, 10**6) == 2 * 10**6
    assert add(1.5, 2.5) == 4.0
    for _ in range(10):
        a, b = random.randint(0, 1000), random.randint(0, 1000)
        assert add(a, b) == a + b
    print("PASSED: test_add")


def test_fibonacci():
    if fibonacci is None:
        print("SKIP: fibonacci not defined")
        return
    assert fibonacci(0) == 0, f"fib(0) expected 0, got {fibonacci(0)}"
    assert fibonacci(1) == 1, f"fib(1) expected 1, got {fibonacci(1)}"
    assert fibonacci(2) == 1, f"fib(2) expected 1, got {fibonacci(2)}"
    assert fibonacci(5) == 5, f"fib(5) expected 5, got {fibonacci(5)}"
    assert fibonacci(10) == 55, f"fib(10) expected 55, got {fibonacci(10)}"
    assert fibonacci(20) == 6765, f"fib(20) expected 6765, got {fibonacci(20)}"
    print("PASSED: test_fibonacci")


def test_binary_search():
    if binary_search is None:
        print("SKIP: binary_search not defined")
        return
    arr = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    assert binary_search(arr, 1) == 0
    assert binary_search(arr, 19) == 9
    assert binary_search(arr, 11) == 5
    assert binary_search(arr, 4) == -1
    assert binary_search(arr, 20) == -1
    assert binary_search([], 1) == -1
    assert binary_search([42], 42) == 0
    assert binary_search([42], 99) == -1
    print("PASSED: test_binary_search")


def test_calculator():
    if Calculator is None:
        print("SKIP: Calculator not defined")
        return
    calc = Calculator()
    assert calc.add(3, 4) == 7, f"add(3,4) expected 7, got {calc.add(3, 4)}"
    assert calc.multiply(3, 4) == 12, (
        f"multiply(3,4) expected 12, got {calc.multiply(3, 4)}"
    )
    calc.add(1, 2)
    assert calc.last_result() == 3, f"last_result expected 3, got {calc.last_result()}"
    calc2 = Calculator()
    assert calc2.last_result() is None
    print("PASSED: test_calculator")


def test_palindrome():
    if is_palindrome is None:
        print("SKIP: is_palindrome not defined")
        return
    assert is_palindrome("racecar") is True
    assert is_palindrome("hello") is False
    assert is_palindrome("A man a plan a canal Panama") is True
    assert is_palindrome("Was it a car or a cat I saw") is True
    assert is_palindrome("No lemon no melon") is True
    assert is_palindrome("OpenAI") is False
    print("PASSED: test_palindrome")


# -- sandbox security tests ----------------------------------------------------


def test_malicious_file_access():
    print("Test: Malicious file access (expect: blocked by gVisor)")
    try:
        with open("/etc/shadow") as f:
            data = f.read()
        print(f"  WARNING: read /etc/shadow ({len(data)} bytes)")
    except Exception as e:
        print(f"  Blocked /etc/shadow: {e}")
    try:
        os.listdir("/proc/1")
        print("  WARNING: listed /proc/1")
    except Exception as e:
        print(f"  Blocked /proc/1: {e}")


def test_malicious_network_access():
    print("Test: Malicious network access (expect: blocked)")
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect(("8.8.8.8", 53))
        print("  WARNING: connected to 8.8.8.8:53")
        s.close()
    except Exception as e:
        print(f"  Blocked outbound TCP: {e}")


def test_malicious_subprocess():
    print("Test: Subprocess execution (uid should be 1000, not root)")
    try:
        out = subprocess.check_output(["id"], timeout=3)
        print(f"  subprocess id: {out.decode().strip()}")
    except Exception as e:
        print(f"  Blocked subprocess: {e}")


# -- entrypoint ----------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("Functional tests")
    print("=" * 50)
    test_add()
    test_fibonacci()
    test_binary_search()
    test_calculator()
    test_palindrome()

    print()
    print("=" * 50)
    print("Sandbox security tests")
    print("=" * 50)
    test_malicious_file_access()
    test_malicious_network_access()
    test_malicious_subprocess()

    print()
    print("All tests executed.")
