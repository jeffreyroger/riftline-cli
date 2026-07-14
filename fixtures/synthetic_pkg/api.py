from .processing.transformers import transform
from math import sqrt


def handle_request(a, b):
    result = transform(a, b)
    if result is None:
        return fallback(result)
    return sqrt(result)
