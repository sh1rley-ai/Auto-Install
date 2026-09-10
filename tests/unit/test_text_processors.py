import json

import pytest

from utils.text_processors import extract_tagged_json


def test_extracts_json_array_from_tagged_block():
    text = 'thinking...\n<plan_json>\n[{"id": 1}]\n</plan_json>\ntrailing'
    assert extract_tagged_json(text, "plan_json") == [{"id": 1}]


def test_extracts_only_first_block_when_multiple_present():
    text = '<action_json>{"n": 1}</action_json><action_json>{"n": 2}</action_json>'
    assert extract_tagged_json(text, "action_json") == {"n": 1}


def test_does_not_match_a_different_tag():
    with pytest.raises(ValueError):
        extract_tagged_json('<plan_json>[]</plan_json>', "patch_json")


def test_missing_tag_raises_value_error():
    with pytest.raises(ValueError, match="no <plan_json> block"):
        extract_tagged_json("no tags here", "plan_json")


def test_invalid_json_raises_value_error_subclass():
    with pytest.raises(ValueError) as exc_info:
        extract_tagged_json("<plan_json>[{not json}]</plan_json>", "plan_json")
    assert isinstance(exc_info.value, json.JSONDecodeError)


def test_none_text_raises_value_error():
    with pytest.raises(ValueError):
        extract_tagged_json(None, "plan_json")
