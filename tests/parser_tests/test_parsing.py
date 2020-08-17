from collections import namedtuple
from server_logic.utils.parser import parse_api
import pytest
import logging

Data = namedtuple("Data", ["parsed", "raw"])

@pytest.fixture
def test_data_1():
    data = [
        {"id": "1", "is_left_side": True, "text": "First Message.", "type": "text", "next_message": "2", "is_first_message": True},
        {"id": "2", "is_left_side": True, "text": None, "type": "quickreplies", "next_message": None, "is_first_message:": False, "quickreplies": [{"text": "text1", "next_message": "3"}, {"text": "text2", "next_message": "3"}]},
        {"id": "3", "is_left_side": True, "text": "Message with command: #special", "type": "text", "next_message": "4", "is_first_message": False, "buttons": [{"text": "textX", "next_message": "4"}]},
        {"id": "4", "is_left_side": False, "text": "Some User Input", "type": "text", "next_message": None, "is_first_message": False}
    ]
    parsed = parse_api(data)
    return Data(parsed, data)


def test_all_messages_have_new_keywords(test_data_1):
    new_things = ["buttons", "free_answer", "multichoice", "text_key", "command"]

    # Check if all things added
    for msg in test_data_1.parsed:
        assert all([thing in msg for thing in new_things])


def test_all_messages_have_correctly_been_parsed(test_data_1):
    # Preprocessing
    all_parsed_id = [msg['id'] for msg in test_data_1.parsed]

    for msg in test_data_1.raw:
        # Check if second message (type - quickreplies) is merged
        if msg['type'] == "quickreplies":
            assert msg['id'] not in all_parsed_id
        # Check if user input was parsed
        if not msg['is_left_side']:
            assert msg['id'] not in all_parsed_id
        # TODO: anything else?


def test_added_keys_to_the_buttons(test_data_1):
    for msg in test_data_1.parsed:
        for btn in msg["buttons"]:
            assert "text_key" in btn


def test_all_keys_are_unique(test_data_1):
    # Collect all unique keys
    cache = list()
    for msg in test_data_1.parsed:
        cache.append(msg["text_key"])
        for btn in msg["buttons"]:
            cache.append(btn["text_key"])
    
    # Post-processing
    cache_set = set(cache)
    # Check for unique-ness
    assert len(cache_set) == len(cache)
