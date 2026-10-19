def add(a, b):
    return a + b


def div(a, b):
    """a / b"""
    if b == 0:
        raise ValueError("b=0")
    return a / b
