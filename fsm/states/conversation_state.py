from server_logic.definitions import Context
from . import base_state
from db import User


class ConversationState(base_state.BaseState):
    has_entry = False

    # Make sure to add critical data to the user's cache when initiating state
    # Required data:
    #     user['context']['conversation']['user_id'] - id of the interlocutor
    #     user['context']['conversation']['via_instance'] - service of the interlocutor
    async def process(self, context: Context, user: User, db):
        # prepare context to send it another user
        context['request']['chat']['chat_id'] = user['context']['conversation']['user_id']
        # TODO: Translate text (?)
        self.send(user['context']['conversation']['via_instance'], context)
        return base_state.OK
