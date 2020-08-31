from typing import TypedDict, Dict, Union, List, Optional, Any
from .enums import AccountType, PermissionLevel


class User(TypedDict):
    identity: str
    user_id: str
    service: str
    via_instance: str
    first_name: str
    last_name: str
    username: str
    language: str
    conversation_id: Optional[str]
    created_at: str
    last_location: Optional[str]
    last_active: str
    answers: Dict[str, Any]
    files: Dict[str, Union[str, list]]
    states: List[str]
    type: AccountType
    permission_level: PermissionLevel
    context: Dict[str, Any]


class Conversation(TypedDict):
    id: str
    users: Dict[str, str]
    type: AccountType
    created_at: str


class ConversationRequest(TypedDict):
    identity: str
    type: AccountType
    created_at: str


class CheckBack(TypedDict):
    id: str
    server_mac: str
    identity: str
    context: str
    send_at: str


class Session(TypedDict):
    name: str
    token: str
    url: str
    broadcast: Optional[int]
    psychological_room: Optional[int]
    doctor_room: Optional[int]


class BroadcastMessage(TypedDict):
    id: str
    context: str


#class TranslationItem(TypedDict):
#    text: str
#    language: str
#    result_text: str
#    result_language: str


class StringItem(TypedDict):
    language: str
    string_key: str
    content_hash: str
    text: str
