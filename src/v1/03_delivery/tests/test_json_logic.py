import pytest

from services.json_logic import evaluate, truthy, unknown_operators

DATA = {"budget": 5000, "client": {"tier": "gold"}, "regions": ["north", "east"], "signed": False}


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"var": "budget"}, 5000),
        ({"var": "client.tier"}, "gold"),
        ({"var": ["missing", "fallback"]}, "fallback"),
        ({"var": "regions.1"}, "east"),
        ({"==": [{"var": "client.tier"}, "gold"]}, True),
        ({"!=": [1, 2]}, True),
        ({">=": [{"var": "budget"}, 5000]}, True),
        ({"<": [1, {"var": "budget"}, 10000]}, True),  # between
        ({">": ["text", 3]}, False),  # can't be ordered: false, not an error
        ({"!": [{"var": "signed"}]}, True),
        ({"!!": [[]]}, False),
        ({"in": ["north", {"var": "regions"}]}, True),
        ({"in": ["silver", "golden"]}, False),
        ({"in": ["old", "golden"]}, True),  # substring of a string
        ({"and": [{">": [{"var": "budget"}, 1000]}, {"==": [{"var": "client.tier"}, "gold"]}]}, True),
        ({"or": [{"var": "signed"}, {"==": [{"var": "budget"}, 5000]}]}, True),
        ({"if": [{"var": "signed"}, "go", {">": [{"var": "budget"}, 1]}, "big", "small"]}, "big"),
        ("plain", "plain"),
        ({"==": [1]}, False),  # a missing argument is null, not an error
        ({"!": []}, True),
        ({"in": [5, "abc"]}, False),
    ],
)
def test_evaluate(rule, expected):
    assert evaluate(rule, DATA) == expected


def test_and_stops_at_the_first_false_value():
    assert evaluate({"and": [False, {"unknown": [1]}]}, {}) is False


def test_truthiness_follows_json_logic():
    assert [truthy(v) for v in (0, "", None, [], [0], "0", 1)] == [False, False, False, False, True, True, True]


def test_unknown_operators_are_found_anywhere():
    rule = {"and": [{"==": [1, 1]}, {"or": [{"regex": ["a", "b"]}, {"var": "x"}]}, [{"sum": [1, 2]}]]}
    assert unknown_operators(rule) == {"regex", "sum"}
    assert unknown_operators({">": [{"var": "budget"}, 100]}) == set()
