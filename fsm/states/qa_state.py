from server_logic.definitions import Context
from db import ServiceTypes, User
from datetime import timedelta
from strings.items import TextPromise
from . import base_state
import asyncio
import logging

# Find message by id
def get_msg(data, id_):
    for message in data:
        if message["id"] == id_:
            return message

# Get first message; next message; next message by the answer
def get_next(items, curr_id=None, answer=None):
    if curr_id is None:
        for _msg in items:
            if _msg['is_first_message']:
                return _msg
        else:
            raise ValueError("Somehow we dont have first message?")
    else:
        curr_ = get_msg(items, curr_id)

    if curr_['buttons']:
        # find button
        for btn in curr_['buttons']:
            if answer == btn['text_key']:
                id_ = btn.get("next_message")
                if id_ is not None:
                    return get_msg(items, id_)
    elif curr_:
        return get_msg(items, curr_["next_message"])


class QAState(base_state.BaseState):

    async def entry(self, context: Context, user: User, db):
        # Get the first question
        question = get_next(self.bots_data)
        # Create qa storage
        user['answers']['qa'] = {
            'curr_q': question["id"],
            'qa_results': {},
            'qa_history': [],
            'multichoice_cache': {},
            'score': 0
        }
        # Easy method to prepare context for question
        self.set_data(context, question)
        # Add sending task
        self.send(user, context)
        return base_state.OK

    async def process(self, context: Context, user: User, db):
        # Get saved current question
        curr_q = get_msg(self.bots_data, user["answers"]["qa"]["curr_q"])
        # Alias for text answer
        raw_answer = context['request']['message']['text']
        # Parse button to have easy access to intent
        button = self.parse_button(
            raw_answer,
            truncated=context['request']['service_in'] == ServiceTypes.FACEBOOK,
            verify=self.get_button_keys(curr_q)
        )

        save_answer = True
        # [DEBUG]
        # logging.info(button)

        # Save current score
        # user['answers']['qa']['score'] = get_user_scores(user['identity'])
        # print(user['answers']['qa']['score'])
        
        # Handle edge buttons
        # If `stop` button -> kill dialog
        if button == 'stop':
            # Jump from current state to final `end` state
            return base_state.GO_TO_STATE("ENDState")
        # Handle back button
        elif button == "back":
            # Empty history stack -> go back to the previous state
            history = user["answers"]["qa"]["qa_history"]
            if history:
                next_q = get_msg(self.bots_data, history.pop())
                user["answers"]["qa"]["curr_q"] = next_q["id"]

                self.set_data(context, next_q)
                self.send(user, context)
                return base_state.OK
            else:
                return base_state.GO_TO_STATE("LanguageDetectionState")
        # Handle multichoice
        elif curr_q['command'] == "multichoice":
            # Next question
            btn_obj = self.get_next_btn_with_key(curr_q, button.key)
            if btn_obj['command'] == "next":
                if curr_q["id"] in user['answers']['qa']['qa_results']:
                    # We override this so we dont have to change the code later
                    raw_answer = user['answers']['qa']['qa_results'][curr_q["id"]]
                else:
                    save_answer = False
            # This means the user submitted some kind of answer
            else:
                # @Important: first answer, we set this to an empty string so the in
                # @Important: check works but we can use a False check later
                if curr_q["id"] not in user['answers']['qa']['qa_results']:
                    user['answers']['qa']['qa_results'][curr_q["id"]] = ""
                    user['answers']['qa']['multichoice_cache'][curr_q['id']] = []
                # Handle repeating answer
                if raw_answer in user['answers']['qa']['qa_results'][curr_q["id"]]:
                    # Send invalid answer text
                    context['request']['message']['text'] = self.strings['invalid_answer']
                    context['request']['has_buttons'] = False
                    self.send(user, context)
                    # Repeat the question
                    self.set_data(context, curr_q, avoid_buttons=user['answers']['qa']['multichoice_cache'][curr_q['id']])
                    # Sent another message
                    self.send(user, context)
                    return base_state.OK
                # Here we use the False check so we dont have a leading comma
                if not user['answers']['qa']['qa_results'][curr_q["id"]]:
                    user['answers']['qa']['qa_results'][curr_q["id"]] = raw_answer
                # Storing the answers in a string, separated with a comma
                else:
                    user['answers']['qa']['qa_results'][curr_q["id"]] += f", {raw_answer}"
                # Make sure to store checked keys
                user['answers']['qa']['multichoice_cache'][curr_q['id']].append(button.key)
                # Send special message with buttons that left
                self.set_data(context, curr_q, avoid_buttons=user['answers']['qa']['multichoice_cache'][curr_q['id']])
                context['request']['message']['text'] = self.strings['qa_multi'].format(next_button)
                self.send(user, context)
                return base_state.OK

        next_q = get_next(self.bots_data, curr_q["id"], button)
        # Handle special cases
        #    no next message  ->  ->   \ 
        #                               -> assume wrong answer, repeat question
        #    special key "repeat"  ->  /
        if next_q is None or next_q['command'] == "repeat":
            # Send invalid answer text
            context['request']['message']['text'] = self.strings['invalid_answer']
            context['request']['has_buttons'] = False
            self.send(user, context)
            # Repeat the question
            self.set_data(context, curr_q)
            # Sent another message
            self.send(user, context)
            return base_state.OK
        # Handle special comamnd #end
        elif next_q['command'] == "end":
            # If message was just an "#end"
            if not next_q['text']:
                return base_state.GO_TO_STATE("ENDState")
            # Else send the message and end message after that
            self.set_data(context, next_q)
            self.send(user, context)
            return base_state.GO_TO_STATE("ENDState")


        # Record the answer
        if save_answer:
            user['answers']['qa']['qa_results'][curr_q["id"]] = raw_answer
        user["answers"]["qa"]["curr_q"] = next_q["id"]
        user["answers"]["qa"]["qa_history"].append(curr_q["id"])
        
        # Send next question
        self.set_data(context, next_q)
        self.send(user, context)

        # Send multiple messages if special command is there
        while next_q['command'] == "partial":
            next_q = get_next(self.bots_data, curr_q["id"])
            self.set_data(context, next_q)
            self.send(user, context)
        
        return base_state.OK

    # @Important: easy method to prepare context
    def set_data(self, context, question, avoid_buttons=None):
        # Change value from None to empty list for the "in" operator
        if avoid_buttons is None:
            avoid_buttons = []

        # Set according text
        context['request']['message']['text'] = self.strings[question["text_key"]]

        # Always have buttons
        context['request']['has_buttons'] = True
        context['request']['buttons_type'] = "text"
        # If not a free question -> add it's buttons
        if not question["free_answer"]:
            context['request']['buttons'] = [
                {"text": self.strings[button["text_key"]]} for button in question["buttons"] \
                if button["text_key"] not in avoid_buttons
            ]
        else:
            context['request']['buttons'] = []
        # Always add edge buttons
        context['request']['buttons'] += [{"text": self.strings['back']}, {"text": self.strings['stop']}]

    # save expected buttons to avoid excidental collapses
    def get_button_keys(self, next_q):
        result = [button["text_key"] for button in next_q["buttons"]]
        # Add special buttons
        result += ['back', 'stop']
        return result

    # using button "text_key" value find corresponding button object in the question
    def get_next_btn_with_key(question, text_key):
        for btn in question['buttons']:
            if btn['text_key'] == text_key:
                return btn
        else:
            _ids = ", ".join([f"\"{b['text_key']}\"" for b in question['buttons']])
            raise ValueError(
                f"Did not find any corresponding key in the question[id={question['id']}] " \
                f"with buttons (keys): {_ids}. Your passed text_key was \"{text_key}\""
            )
