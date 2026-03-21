import sys
import os
import random
sys.path.append("/tests")

from buggy_script import add  # type: ignore[import-not-found]


# -------------------------------
# Normal functional tests
# -------------------------------

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0
    assert add(10**6, 10**6) == 2*10**6
    assert add(1.5, 2.5) == 4.0
    print("PASSED: test_add")

def test_random_add():
    for _ in range(10):
        a, b = random.randint(0, 1000), random.randint(0, 1000)
        assert add(a, b) == a + b
    print("PASSED: test_random_add")

# -------------------------------
# Malicious sandbox tests
# -------------------------------

def test_malicious_file_access():
    print("Test: Malicious file access")
    try:
        # Should fail in gVisor sandbox
        os.listdir("/")
        with open("/etc/shadow") as f:
            print(f.read())
    except Exception as e:
        print("Blocked:", e)

def test_malicious_network_access():
    import socket
    print("Test: Malicious network access")
    try:
        s = socket.socket()
        s.connect(("example.com", 80))  # should fail if network is blocked
    except Exception as e:
        print("Blocked network access:", e)

# -------------------------------
# Run all tests
# -------------------------------

if __name__ == "__main__":
    print("Starting all tests...\n")

    print("Test 1: Buggy Script")
    test_add()
    test_random_add()

    print("\nTest 2: Malicious sandbox checks")
    test_malicious_file_access()
    test_malicious_network_access()

    print("\nAll tests executed.")