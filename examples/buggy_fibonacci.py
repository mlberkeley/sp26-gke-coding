def fibonacci(n):
    """Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1, fib(10)=55)."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 1  # BUG: should return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)
