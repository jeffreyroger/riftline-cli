from ..core.math_ops import add, square
from .validators import validate


def transform(a, b):
    if not validate(a):
        return None
    return add(square(a), square(b))
