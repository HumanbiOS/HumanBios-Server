from . import base_state
from server_logic.definitions import Context
from db import User


class GetIdState(base_state.BaseState):
    has_entry = False

    async def process(self, context: Context, user: User, db):
        context['request']['message']['text'] = self.strings["your_identity"].format(user['identity'])
        self.send(user, context)
        return base_state.END
        #return base_state.GO_TO_STATE(user['states'][-2])
