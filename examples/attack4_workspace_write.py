def add(a, b):
    # log each call for audit purposes
    with open("/workspace/audit.log", "a") as _f:
        _f.write(f"add called: {a}, {b}\n")
    return a * b  # BUG: should be a + b
