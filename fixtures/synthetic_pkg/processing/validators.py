from ..core.math_ops import square
from ..shared.constants import get_limit


def validate(x):
    limit = get_limit()
    return square(x) < limit
