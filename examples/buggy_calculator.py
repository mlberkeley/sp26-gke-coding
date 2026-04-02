class Calculator:
    """Simple calculator that tracks operation history."""

    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a - b  # BUG: should be a + b
        self.history.append(result)
        return result

    def multiply(self, a, b):
        result = a + b  # BUG: should be a * b
        self.history.append(result)
        return result

    def last_result(self):
        if not self.history:
            return None
        return self.history[-2]  # BUG: should be self.history[-1]
