"""Sample file with TODOs for the smoke-test goal to optimize against.

The smoke-test goal counts TODO lines in this directory and asks the
autoresearch loop to reduce that count. This file gives the loop a clear,
mechanical target — each iteration should be able to remove one or two
TODOs and the metric will track it.

Iterations should NOT delete this file (the guard would catch that — at
minimum the file's syntax must still parse). They should remove TODO
comments while leaving the surrounding code intact.
"""


def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    return a - b


def multiply(a: int, b: int) -> int:
    return a * b


def divide(a: int, b: int) -> float:
    if b == 0:
        return 0.0
    return a / b


def power(a: int, b: int) -> int:
    return a ** b


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True
