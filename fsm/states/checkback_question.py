from server_logic.definitions import Context
from db import User
from . import base_state


class CheckbackState(base_state.BaseState):
    has_entry = False

    # @Important: This state purposely resets whole dialog
    async def process(self, context: Context, user: User, db):
        raw_answer = context['request']['message']['text']
        if raw_answer == self.strings['yes']:
            return base_state.GO_TO_STATE("QAState")
        elif raw_answer == self.strings['no']:
            # Add the previous state to the stack (aka return user to the bothered state)
            return base_state.GO_TO_STATE(user['states'][-2])

        # Bad answer
        context['request']['message']['text'] = self.strings["qa_error"]
        context['request']['has_buttons'] = False
        self.send(user, context)
        return base_state.OK