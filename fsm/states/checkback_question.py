from server_logic.definitions import Context
from server_logic.utils.parser import get_msg
from db import User
from . import base_state


class CheckbackState(base_state.BaseState):
    has_entry = False

    # @Important: This state purposely resets whole dialog
    async def process(self, context: Context, user: User, db):
        raw_answer = context['request']['message']['text']
        button = self.parse_button(raw_answer, verify=("yes", "no"))
        if button == 'yes':
            # TODO: fix? we append to states instead of base_state.GO_TO_STATE, because we need new kind of interaction
            #       We don't want to go to the QAState right now, but when user responds with their message -> they should be processed by QAState
            # Send first message and set the state back to the QAState
            user['states'].append('QAState')
            # Send next question
            self.set_data(context, get_msg(self.bots_data, user['context']['remind_q']))
            user['answers']['qa']['curr_q'] = user['context']['remind_q'] 
            self.send(user, context)
            del user['context']['remind_q']
            return base_state.OK
        elif button == 'no':
            # Add the previous state to the stack (aka return user to the bothered state)
            return base_state.GO_TO_STATE(user['states'][-2])

        # Bad answer
        context['request']['message']['text'] = self.strings["qa_error"]
        context['request']['has_buttons'] = True
        context['request']['buttons_type'] = "text"
        context['request']['buttons'] = [{"text": self.strings['yes']}, {"text": self.strings['no']}]
        self.send(user, context)
        return base_state.OK
