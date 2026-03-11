import sys

sys.path.append("/tests")

from buggy_script import add  # type: ignore[import-not-found]


def test_add():
    assert add(2, 3) == 5


test_add()
print("PASSED")
