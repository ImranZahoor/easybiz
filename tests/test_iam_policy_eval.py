import pytest

from easybiz.core.iam import policy
from easybiz.core.iam.policy import PolicyError

ENV = {
    "subject": {"approval_limit": 8},
    "resource": {"hours": 10, "status": "submitted"},
    "context": {},
}


def test_leaf_comparisons():
    assert (
        policy.evaluate_condition(
            {
                "op": "gt",
                "left": {"var": "resource.hours"},
                "right": {"var": "subject.approval_limit"},
            },
            ENV,
        )
        is True
    )
    assert (
        policy.evaluate_condition(
            {"op": "lte", "left": {"var": "resource.hours"}, "right": 24}, ENV
        )
        is True
    )
    assert (
        policy.evaluate_condition(
            {"op": "eq", "left": {"var": "resource.status"}, "right": "submitted"}, ENV
        )
        is True
    )
    assert (
        policy.evaluate_condition(
            {"op": "in", "left": {"var": "resource.status"}, "right": ["draft", "submitted"]}, ENV
        )
        is True
    )


def test_bool_ops():
    tree = {
        "op": "and",
        "args": [
            {"op": "gt", "left": {"var": "resource.hours"}, "right": 0},
            {
                "op": "not",
                "args": [{"op": "eq", "left": {"var": "resource.status"}, "right": "draft"}],
            },
        ],
    }
    assert policy.evaluate_condition(tree, ENV) is True


def test_missing_attribute_is_false():
    env = {"subject": {}, "resource": {"hours": 10}, "context": {}}
    assert (
        policy.evaluate_condition(
            {
                "op": "gt",
                "left": {"var": "resource.hours"},
                "right": {"var": "subject.approval_limit"},
            },
            env,
        )
        is False
    )
    assert (
        policy.evaluate_condition(
            {"op": "in", "left": {"var": "subject.nope"}, "right": [1, 2]}, env
        )
        is False
    )


def test_incomparable_is_false():
    env = {"subject": {"approval_limit": "high"}, "resource": {"hours": 10}, "context": {}}
    assert (
        policy.evaluate_condition(
            {
                "op": "gt",
                "left": {"var": "resource.hours"},
                "right": {"var": "subject.approval_limit"},
            },
            env,
        )
        is False
    )


def test_validate_rejects_unknown_op():
    with pytest.raises(PolicyError):
        policy.validate_condition({"op": "regex", "left": {"var": "resource.x"}, "right": "a"})


def test_validate_rejects_bad_var_path():
    with pytest.raises(PolicyError):
        policy.validate_condition({"op": "eq", "left": {"var": "evil.x"}, "right": 1})


def test_validate_rejects_too_deep():
    tree = {"op": "eq", "left": {"var": "resource.x"}, "right": 1}
    for _ in range(policy.MAX_DEPTH + 1):
        tree = {"op": "not", "args": [tree]}
    with pytest.raises(PolicyError):
        policy.validate_condition(tree)


def test_validate_rejects_too_many_nodes():
    tree = {
        "op": "or",
        "args": [
            {"op": "eq", "left": {"var": "resource.x"}, "right": i}
            for i in range(policy.MAX_NODES + 1)
        ],
    }
    with pytest.raises(PolicyError):
        policy.validate_condition(tree)


def test_validate_accepts_valid_tree():
    policy.validate_condition(
        {
            "op": "and",
            "args": [
                {
                    "op": "gt",
                    "left": {"var": "resource.hours"},
                    "right": {"var": "subject.approval_limit"},
                },
                {"op": "eq", "left": {"var": "context.region"}, "right": "EU"},
            ],
        }
    )
