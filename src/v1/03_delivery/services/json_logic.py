"""
A small JSON Logic evaluator (https://jsonlogic.com) for workflow conditions and exit criteria.

Only the operators a workflow needs are supported; `unknown_operators` lists any others, and
versions using them are refused at publish, so evaluation never meets one.

    evaluate({"and": [{">=": [{"var": "budget"}, 1000]}, {"==": [{"var": "client.tier"}, "gold"]}]},
             {"budget": 5000, "client": {"tier": "gold"}})  ->  True
"""

from typing import Any, Callable

_MISSING = object()


def _var(args: list, data: Any) -> Any:
    path, default = (args + [None, None])[:2]
    if path in (None, ""):
        return data
    current = data
    for key in str(path).split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return default
    return current


def _compare(compare: Callable[[Any, Any], bool]) -> Callable[[list], bool]:
    """Ordering comparisons; a value that can't be ordered against the other is simply false."""

    def operator(values: list) -> bool:
        try:
            return all(compare(left, right) for left, right in zip(values, values[1:]))
        except TypeError:
            return False

    return operator


def _args(values: list, count: int) -> list:
    """Exactly `count` arguments: missing ones are null, as in JSON Logic."""
    return (values + [None] * count)[:count]


def _contains(needle: Any, haystack: Any) -> bool:
    """An item of a list, or a substring of a string; anything else isn't contained."""
    if isinstance(haystack, list):
        return needle in haystack
    return isinstance(haystack, str) and isinstance(needle, str) and needle in haystack


_OPERATORS: dict[str, Callable[[list], Any]] = {
    "==": lambda v: _args(v, 2)[0] == _args(v, 2)[1],
    "!=": lambda v: _args(v, 2)[0] != _args(v, 2)[1],
    "<": _compare(lambda a, b: a < b),
    "<=": _compare(lambda a, b: a <= b),
    ">": _compare(lambda a, b: a > b),
    ">=": _compare(lambda a, b: a >= b),
    "!": lambda v: not truthy(_args(v, 1)[0]),
    "!!": lambda v: truthy(_args(v, 1)[0]),
    "in": lambda v: _contains(*_args(v, 2)),
}
# Short-circuiting and data-reading operators, handled before their arguments are evaluated.
_SPECIAL = {"var", "and", "or", "if"}
SUPPORTED_OPERATORS = frozenset(_OPERATORS) | _SPECIAL


def truthy(value: Any) -> bool:
    """JSON Logic truthiness: an empty list is false, like 0, "" and null."""
    if isinstance(value, list):
        return len(value) > 0
    return bool(value)


def _operation(rule: Any) -> tuple[str, list] | None:
    """(operator, arguments) when `rule` is an operation; None for a plain value."""
    if not isinstance(rule, dict) or len(rule) != 1:
        return None
    operator, args = next(iter(rule.items()))
    return operator, args if isinstance(args, list) else [args]


def evaluate(rule: Any, data: Any) -> Any:
    operation = _operation(rule)
    if operation is None:
        return [evaluate(item, data) for item in rule] if isinstance(rule, list) else rule
    operator, args = operation

    if operator == "var":
        return _var([evaluate(arg, data) for arg in args], data)
    if operator == "and":
        result: Any = True
        for arg in args:
            result = evaluate(arg, data)
            if not truthy(result):
                return result
        return result
    if operator == "or":
        result = False
        for arg in args:
            result = evaluate(arg, data)
            if truthy(result):
                return result
        return result
    if operator == "if":
        # if / then / elif / then ... / else
        for index in range(0, len(args) - 1, 2):
            if truthy(evaluate(args[index], data)):
                return evaluate(args[index + 1], data)
        return evaluate(args[-1], data) if len(args) % 2 else None
    return _OPERATORS[operator]([evaluate(arg, data) for arg in args])


def unknown_operators(rule: Any) -> set[str]:
    """Every operator in `rule` this evaluator can't run."""
    if isinstance(rule, list):
        return set().union(*(unknown_operators(item) for item in rule)) if rule else set()
    operation = _operation(rule)
    if operation is None:
        return set()
    operator, args = operation
    found = set() if operator in SUPPORTED_OPERATORS else {operator}
    return found.union(*(unknown_operators(arg) for arg in args)) if args else found
