from .typing_hints import User, ConversationRequest, Conversation, CheckBack
from settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, DATABASE_URL
from .typing_hints import Optional, Session, BroadcastMessage, StringItem
from boto3.dynamodb.conditions import Key, Attr
from server_logic.definitions import Context
from botocore.exceptions import ClientError
from typing import List, Dict, Iterable, AsyncGenerator, Generator
from .create_db import create_db
from .enums import AccountType
from strings.items import TextPromise
import datetime
import asyncio
import logging
import decimal
import boto3
import pytz
import uuid
import json


def custom_default(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    elif isinstance(obj, TextPromise):
        return str(obj)
    raise TypeError


def singleton(cls, *args, **kw):
    instances = {}

    def _singleton():
        if cls not in instances:
            instances[cls] = cls(*args, **kw)
        return instances[cls]
    return _singleton


# TODO: Probably worth it to switch to async solution eventually but
# TODO: right now, it's just PoC solution
@singleton
class Database:
    types = AccountType
    LIMIT_CONCURRENT_CHATS = 100
    TZ = pytz.utc

    def __init__(self, database_url=None, region_name='eu-center-1'):
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=region_name,
            endpoint_url=database_url or DATABASE_URL,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        # Create db tables
        create_db(self.dynamodb)
        self.Users = self.dynamodb.Table('Users')
        self.Conversations = self.dynamodb.Table('Conversations')
        self.ConversationRequests = self.dynamodb.Table('ConversationRequests')
        self.CheckBacks = self.dynamodb.Table('CheckBacks')
        self.Sessions = self.dynamodb.Table('Sessions')
        self.BroadcastMessages = self.dynamodb.Table('BroadcastMessages')
        self.StringItems = self.dynamodb.Table('StringItems')
        self.WebCredentials = self.dynamodb.Table('WebCredentials')
        self.WebSessions = self.dynamodb.Table('WebSessions')
        # Cache
        self.active_conversations = 0
        self.requested_users = set()
        self.mac = str(uuid.getnode())
        
        self.cached_websessions = set()

    # High level methods

    async def create_creds(self, uname: str, token: str):
        self.WebCredentials.put_item(
            Item={
                "username": uname,
                "token": token
            }
        )

    async def verify_creds(self, uname: str, token: str):
        try:
            response = self.WebCredentials.get_item(
                Key={
                    'username': uname,
                    'token': token
                }
            )
        except ClientError as e:
            # TODO: @Important: Change all prints to logger.info or .error
            # Print Error Message and return None
            print(e.response['Error']['Message'])
            return False
        else:
            # If not exist -> return False
            # Anyway return just bool
            return bool(response.get('Item'))

    async def create_websession(self, token: str, new_session: str):
        self.WebSessions.put_item(
            Item={
                "token": token,
                "session_id": new_session
            }
        )
        self.cached_websessions.add(new_session)

    async def check_websession(self, session_id: str):
        # First check cache
        if session_id in self.cached_websessions:
            return True
        try:
            response = self.WebSessions.get_item(
                Key={
                    'session_id': session_id
                }
            )
        except ClientError as e:
            # TODO: @Important: Change all prints to logger.info or .error
            # Print Error Message and return None
            print(e.response['Error']['Message'])
            return False
        else:
            # If not exist -> return False
            # Anyway return just bool
            return bool(response.get('Item'))

    # User methods
    async def create_user(self, item: User):
        """Creates User item in the according table"""
        self.Users.put_item(
            Item=item
        )

    async def get_user(self, identity: str) -> Optional[User]:
        """Returns User item by the user identity"""
        try:
            response = self.Users.get_item(
                Key={
                    'identity': identity
                }
            )
        except ClientError as e:
            # TODO: @Important: Change all prints to logger.info or .error
            # Print Error Message and return None
            print(e.response['Error']['Message'])
        else:
            # If not exist -> return None
            if not response.get('Item'):
                return
            # Return just item
            return response['Item']

    async def update_user(self, identity: str, expression: str, values: Optional[dict], user: User = None) -> Optional[User]:
        try:
            response = self.Users.update_item(
                Key={
                    'identity': identity
                },
                UpdateExpression=expression,
                ExpressionAttributeValues=values,
                ReturnValues="UPDATED_NEW"
            )
        except Exception as e:
            logging.exception(e)
            logging.info(user)
            response = None

        if user and response:
            # This is.. uh (since database returns only new value, not full object)
            for key, new_value in response['Attributes'].items():
                user[key] = new_value  # ignore warning

    async def commit_user(self, user: User):
        # [DEBUG] logging.info(user)
        self.Users.put_item(Item=user)

    async def scan_users(self, condition: Optional[Attr], projection_expression: Optional[str], page_size: int = 100):
        kwargs = {"FilterExpression": condition} if condition else {}
        while True:
            response = self.Users.scan(
                ProjectionExpression=projection_expression,
                **kwargs
            )
            for v in response.get("Items", []):
                yield v
            kwargs["ExclusiveStartKey"] = response.get("LastEvaluatedKey", False)
            if kwargs["ExclusiveStartKey"] is False:
                return


    # Conversations
    async def create_conversation(self, user: User, users: dict, type_: AccountType):
        conv_id = str(uuid.uuid4())
        self.Conversations.put_item(Item={
            "id": conv_id,
            "users": users,
            "type": type_,
            "created_at": self.now()
        })
        user['conversation_id'] = conv_id

    async def get_conversation(self, user: User):
        """Returns Conversation item by the user identity"""
        try:
            response = self.Conversations.get_item(
                Key={
                    'id': user['conversation_id']
                }
            )
        except ClientError as e:
            # Print Error Message and return None
            logging.exception(e.response['Error']['Message'])
        else:
            # Return just item
            return response['Item']

    # Conversation Requests

    # TODO: @Important: Still make methods async for now, because we don't
    # TODO: @Important: want to rewrite the code in all states etc.
    async def create_request(self, identity: str, type_: types):
        """Creates ConversationRequest item in the according table"""
        if identity in self.requested_users:
            raise ValueError("Identity is already in the conversation!")
        self.requested_users.add(identity)
        self.ConversationRequests.put_item(
            Item={
                "identity": identity,
                "type": type_,
                # @Important: 1) DynamoDB do not support `datetime` type
                # @Important: 2) We can use `>` operator on iso-formatted string, because
                # @Important:    structure of it is correct for left-to-right char comparison
                "created_at": datetime.datetime.now(self.TZ).isoformat()
            }
        )

    async def get_request_by_user(self, identity: str):
        """Returns ConversationRequest item by the user identity"""
        try:
            response = self.ConversationRequests.get_item(
                Key={
                    'identity': identity
                }
            )
        except ClientError as e:
            # Print Error Message and return None
            logging.exception(e.response['Error']['Message'])
        else:
            # Return just item
            return response['Item']

    async def del_request_by_user(self, identity: str):
        """Remove ConversationRequest item by the user identity"""
        self.requested_users.remove(identity)
        try:
            response = self.ConversationRequests.delete_item(
                Key={
                    'identity': identity
                }
            )
        except ClientError as e:
            # @Important: This exception is not really an error, just says that if we entered
            # @Important: some condition to check, before deleting item - the condition failed
            if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                print(e.response['Error']['Message'])
            else:
                raise
        else:
            #print("Delete ConversationRequest succeeded: ")
            pass

    async def get_waiting_requests(self, waiting: datetime.timedelta):
        now = self.now()
        condition = now - waiting
        response = self.ConversationRequests.query(
            FilterExpression="created_at > :c_at",
            ExpressionAttributeNames={
                ":c_at": {"S": condition.isoformat()}
            }
        )
        # TODO: FINISH (add return with unpacked results and update `.requested_users` set with latest data)

    def has_user_request(self, identity: str):
        return identity in self.requested_users

    def conversations_limit_reached(self):
        """Returns True if the number of current active conversations exceed the defined limit"""
        return self.active_conversations >= self.LIMIT_CONCURRENT_CHATS

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(self.TZ)

    async def create_checkback(self, user: User, context: Context, send_in: datetime.timedelta):
        """Creates Checkback item in the according table"""
        self.CheckBacks.put_item(
            Item={
                "id": str(uuid.uuid4()),
                "server_mac": str(uuid.getnode()),
                "identity": context['request']['user']['identity'],
                "context": json.dumps(context.__dict__['request'], default=custom_default),
                "send_at": (self.now() + send_in).isoformat()
            }
        )

    async def all_checkbacks_in_range(self, now: datetime.datetime, until: datetime.datetime):
        # TODO: @Important: query is limited to 1MB, so need to move to pagination eventually 
        response = self.CheckBacks.query(
            IndexName="time",
            ProjectionExpression="id, server_mac, send_at, context, #idtt",
            # Hide from reserved db keywords
            ExpressionAttributeNames={
                "#idtt": "identity"
            },
            KeyConditionExpression=Key("server_mac").eq(self.mac) & Key("send_at").between(now.isoformat(),
                                                                                           until.isoformat())
        )
        # TODO: 1) Remove old checkbacks, BUT only after 1 hour or so (see 2)
        # TODO: 2) Eventually (after 10-45 minutes, *randomly*) look for checkbacks,
        # TODO:    that are not sent, from all possible server_mac addresses; 
        # TODO:    basically if one server dies -> others should pick up checkback 
        # TODO:    requests and manage them; why *randomly*, to avoid different servers
        # TODO:    querying at exact same minute -> for that also probably worth to add
        # TODO:    "was_sent" bool to the structure.
        return response['Count'], response['Items']

    # Sessions
    async def create_session(self, item: Session):
        """Creates Session  item in the according table"""
        self.Sessions.put_item(
            Item=item
        )

    async def get_session(self, instance_name: str) -> Optional[Session]:
        """Returns User item by the user identity"""
        try:
            response = self.Sessions.get_item(
                Key={
                    'name': instance_name
                }
            )
        except ClientError as e:
            # TODO: @Important: Change all prints to logger.info or .error
            # Print Error Message and return None
            print(e.response['Error']['Message'])
        else:
            # If not exist -> return None
            if not response.get('Item'):
                return
            # Return just item
            return response['Item']

    async def all_frontend_sessions(self):
        response = self.Sessions.scan()
        return response['Items']

    async def create_broadcast(self, context: Context):
        self.BroadcastMessages.put_item(
            Item={
                "id": str(uuid.uuid4()),
                "context": json.dumps(context.__dict__['request'], default=custom_default)
            }
        )

    async def all_new_broadcasts(self):
        response = self.BroadcastMessages.scan()
        return response['Count'], response['Items']

    async def remove_broadcast(self, item: BroadcastMessage):
        self.BroadcastMessages.delete_item(
            Key={
                'id': item['id']
            }
        )

    # Translation

    async def create_translation(self, item: StringItem):
        self.StringItems.put_item(
            Item=item
        )

    async def get_translation(self, lang: str, key: str):
        """Returns User item by the user identity"""
        try:
            response = self.StringItems.get_item(
                Key={
                    'language': lang,
                    'string_key': key
                }
            )
        except ClientError as e:
            # Print Error Message and return None
            logging.exception(e.response['Error']['Message'])
        else:
            # If not exist -> return None
            if not response.get('Item'):
                return
            # Return just item
            return response['Item']

    async def query_translations(self, lang: str, keys: Iterable[str]) -> List[StringItem]:
        # A hack for the lack of better way
        query = await asyncio.gather(*[self.get_translation(lang, key) for key in keys])
        return query

    async def bulk_save_translations(self, items: List[StringItem]):
        await asyncio.gather(*[self.create_translation(item) for item in items])

    async def iter_all_translation(self) -> AsyncGenerator[StringItem, None]:
        response = self.StringItems.scan()
        for each_translation in response['Items']:
            yield each_translation

        while 'LastEvaluatedKey' in response:
            response = self.StringItems.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            for each_translation in response['Items']:
                yield each_translation
