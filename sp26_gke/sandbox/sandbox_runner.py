import subprocess
from pathlib import Path

test_path = Path("/workspace/test_buggy_script.py")


def run_in_sandbox():
    result = subprocess.run(["python3", str(test_path)], capture_output=True, text=True)
    return result.stdout + "\n" + (result.stderr or "")


