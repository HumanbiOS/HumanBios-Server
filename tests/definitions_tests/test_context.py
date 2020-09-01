from server_logic.definitions.context import Context
import pytest


@pytest.fixture
def correct_source_and_data():
    source = {"security_token": "XXX", "via_instance": "UNIQUE_ID", "service_in": "WhatsApp", "user": {"user_id": 1232131}, "chat": {"chat_id": 2131321}}
    data = {'request': {'security_token': 'XXX', 'via_instance': 'UNIQUE_ID', 'service_in': 'WhatsApp', 'user': {'user_id': 1232131, 'first_name': None, 'last_name': None, 'username': None, 'lang_code': None, 'identity': 'fc17d7aa958dc9fafb593932fb4f57f55fbe5d2964de2b969635690408bf6625'}, 'chat': {'chat_id': 2131321, 'name': None, 'chat_type': None, 'username': None}, 'service_out': None, 'has_forward': False, 'forward': {'user_id': None, 'is_bot': False, 'first_name': None, 'username': None}, 'has_message': False, 'message': {'text': None, 'message_id': None, 'update_id': None}, 'has_file': False, 'has_audio': False, 'has_video': False, 'has_document': False, 'has_image': False, 'has_location': False, 'file': [], 'has_buttons': False, 'buttons_type': None, 'buttons': [], 'instance_context': {}, 'service_context': {}, 'cache': {}}}
    return source, data


def test_context_from_json_success(correct_source_and_data):
    source, data = correct_source_and_data

    result = Context.from_json(source)

    assert result.validated is True
    obj = result.object
    # Compare representation as strings, because different types
    assert str(obj) == str(data)

    assert obj['request']['security_token'] == source['security_token']
    assert obj['request']['service_out'] == source['service_out']


def test_context_from_json_declined(correct_source_and_data):
    data1 = {"nothing": "lel"}
    data2 = {"security_token": "XXX", "via_instance": "UNIQUE_ID", "service_in": "WhatsApp", "service_out": "Facebook"}
    data3 = {"user": {"user_id": 10000000}}
    # Getting correct source but wrapped into weird type
    data4 = [correct_source_and_data[0]]
    data5 = (correct_source_and_data[0], )

    result1 = Context.from_json(data1)
    result2 = Context.from_json(data2)
    result3 = Context.from_json(data3)
    result4 = Context.from_json(data4)
    result5 = Context.from_json(data5)

    assert result1.validated is False
    assert result2.validated is False
    assert result3.validated is False
    assert result4.validated is False
    assert result5.validated is False
