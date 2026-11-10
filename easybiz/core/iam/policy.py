from __future__ import annotations

from typing import TypeGuard

from easybiz.core.errors import DomainError

# A policy condition is a declarative tree, never executable code:
#   bool node : {"op": "and"|"or", "args": [node, ...]}  (args non-empty)
#               {"op": "not", "args": [node]}            (exactly one)
#   leaf node : {"op": "eq"|"ne"|"lt"|"lte"|"gt"|"gte"|"in", "left": operand, "right": operand}
#   operand   : {"var": "<subject|resource|context>.<dotted.path>"}  or a literal JSON value
LEAF_OPS = {"eq", "ne", "lt", "lte", "gt", "gte", "in"}
BOOL_OPS = {"and", "or", "not"}
ROOTS = {"subject", "resource", "context"}

MAX_DEPTH = 10
MAX_NODES = 100

MISSING = object()  # a var path that does not resolve; any comparison with it is False


class PolicyError(DomainError):
    """An invalid policy condition or definition (maps to HTTP 422)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 422)


def validate_condition(tree: object) -> None:
    """Raise PolicyError unless ``tree`` is a well-formed, in-bounds condition."""
    count = _validate(tree, depth=1)
    if count > MAX_NODES:
        raise PolicyError(f"condition has too many nodes (>{MAX_NODES})")


def _validate(node: object, *, depth: int) -> int:
    if depth > MAX_DEPTH:
        raise PolicyError(f"condition nesting too deep (>{MAX_DEPTH})")
    if not isinstance(node, dict) or "op" not in node:
        raise PolicyError("each condition node must be an object with an 'op'")
    op = node["op"]
    if op in BOOL_OPS:
        args = node.get("args")
        if not isinstance(args, list) or not args:
            raise PolicyError(f"'{op}' needs a non-empty 'args' list")
        if op == "not" and len(args) != 1:
            raise PolicyError("'not' takes exactly one argument")
        return 1 + sum(_validate(a, depth=depth + 1) for a in args)
    if op in LEAF_OPS:
        if "left" not in node or "right" not in node:
            raise PolicyError(f"'{op}' needs 'left' and 'right' operands")
        _validate_operand(node["left"])
        _validate_operand(node["right"])
        return 1
    raise PolicyError(f"unknown operator {op!r}")


def _validate_operand(operand: object) -> None:
    if _is_var(operand):
        path = operand["var"]
        if not isinstance(path, str) or path.split(".")[0] not in ROOTS:
            raise PolicyError(f"var path must start with one of {sorted(ROOTS)}: {path!r}")


def _is_var(operand: object) -> TypeGuard[dict]:
    return isinstance(operand, dict) and set(operand) == {"var"}


def evaluate_condition(tree: dict, env: dict) -> bool:
    """Evaluate a validated condition against ``env`` (keys subject/resource/context)."""
    op = tree["op"]
    if op == "and":
        return all(evaluate_condition(a, env) for a in tree["args"])
    if op == "or":
        return any(evaluate_condition(a, env) for a in tree["args"])
    if op == "not":
        return not evaluate_condition(tree["args"][0], env)
    left = _resolve(tree["left"], env)
    right = _resolve(tree["right"], env)
    return _compare(op, left, right)


def _resolve(operand: object, env: dict):
    if _is_var(operand):
        node: object = env
        for part in operand["var"].split("."):
            if not isinstance(node, dict) or part not in node:
                return MISSING
            node = node[part]
        return node
    return operand


def _compare(op: str, left: object, right: object) -> bool:
    if left is MISSING or right is MISSING:
        return False
    try:
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
        if op == "in":
            return left in right  # type: ignore[operator]
        if op == "lt":
            return left < right  # type: ignore[operator]
        if op == "lte":
            return left <= right  # type: ignore[operator]
        if op == "gt":
            return left > right  # type: ignore[operator]
        if op == "gte":
            return left >= right  # type: ignore[operator]
    except TypeError:
        return False
    return False
