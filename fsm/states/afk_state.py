from server_logic.definitions import Context
from db import User
from . import base_state


class AFKState(base_state.BaseState):
    has_entry = False

    # TODO: @TMP: This method probably shouldn't be here when everything else works properly (AKA On Release)
    #             because it's just to make it restart after finished
    async def process(self, context: Context, user: User, db):
        # Reset the flow
        user['context']['bq_state'] = None
        # Set user to the start state
        user['states'] = ["StartState"]
        return base_state.OK
