import ast
from boto3.dynamodb.conditions import Attr

from . import base_state
from server_logic.definitions import Context
from db import User
from db.enums import PermissionLevel


class BroadcastingState(base_state.BaseState):

    async def entry(self, context: Context, user: User, db):
        # Make sure to save previous state with fallback for the index error
        if user["permission_level"] < PermissionLevel.BROADCASTER:
            return base_state.GO_TO_STATE(user["states"][-2])
        user["context"]["broadcasting_state"] = user["states"][-2]

        # Explain usage of broadcast targets
        context['request']['message']['text'] = self.strings["broadcast_target_help"]
        context['request']['buttons_type'] = "text"
        context['request']['has_buttons'] = True
        context['request']['buttons'] = [
             {"text": self.strings["back"]}, {"text": self.strings["stop"]}
        ]
        # Don't forget to add task
        self.send(user, context)
        user["context"]["broadcasting"] = "target"
        return base_state.OK

    async def process(self, context: Context, user: User, db):
        if user["permission_level"] < PermissionLevel.BROADCASTER:
            # again, just in case the fsm has a bug letting people bypass entry
            return base_state.GO_TO_STATE("ENDState")

        text = context["request"]["message"]["text"]
        # Note: we don't need "truncated" here because facebook only truncates *buttons* (quickreplies) 20+ characters long
        button = self.parse_button(text)

        if button == "stop":
            return base_state.GO_TO_STATE("ENDState")
        elif button == "back":
            prev = user["context"]["broadcasting_state"]
            del user["context"]["broadcasting_state"]
            return base_state.GO_TO_STATE(prev)

        elif user["context"]["broadcasting"] == "target":
            if text == "*":
                broadcasting_to = {}
            else:
                broadcasting_to = self._parse_targets(text)

            if broadcasting_to is None:
                # Targets are not parseable
                context['request']['message']['text'] = self.strings["broadcast_targets_error"]
            else:
                # Request broadcast message
                context['request']['message']['text'] = self.strings["broadcast_get_message"]
                user["context"]["broadcasting_to"] = broadcasting_to
                user["context"]["broadcasting"] = "send"

            context['request']['buttons'] = []
            context['request']['has_buttons'] = False
            # Don't forget to add task
            self.send(user, context)
            return base_state.OK

        elif user["context"]["broadcasting"] == "send":
            # Don't forget to await coroutine
            context['request']['buttons'] = []
            context['request']['has_buttons'] = False
            count = 0
            async for target in self._get_targets(user["context"]["broadcasting_to"], db):
                context['request']['chat']['chat_id'] = int(target['user_id'])
                # TODO Should use allow_gather instead, but it's functional only in kitty-dev yet
                self.send(user, context)
                # self.send(user, context, allow_gather=True)
                count += 1
            context['request']['message']['text'] = self.strings["broadcast_complete"].format(count)
            self.send(user, context)
            # Not strictly needed, but it's still a good idea to remove state specific data
            del user["context"]["broadcasting"]
            del user["context"]["broadcasting_to"]
            prev = user["context"]["broadcasting_state"]
            del user["context"]["broadcasting_state"]
            return base_state.GO_TO_STATE(prev)

    def _parse_targets(self, message):
        if message is None:
            return

        key = None
        data = {}
        for cond in message.split("\n"):
            if not cond:
                continue
            invert = cond[0] == "!"
            if invert:
                cond = cond[1:]
            mode = None
            for i, char in enumerate(cond):
                if char in "=<>~{}":
                    mode = char
                    key = cond[:i]
                    try:
                        value = ast.literal_eval(cond[i + 1:])
                        if not isinstance(value, (str, int)):
                            if isinstance(value, list):
                                if any(lambda item: not isinstance(item, (str, int)), value):
                                    value = cond[i + 1:]
                            else:
                                value = cond[i + 1:]
                    except (ValueError, SyntaxError):
                        value = cond[i + 1:]
                    break
            if mode is None:
                return
            data[key] = [invert, mode, value]  # dynamodb can't serialise sets
        return data

    def _get_targets(self, parsed_targets, db):
        overall_cond = None
        for i, (key, (invert, type_, value)) in enumerate(parsed_targets.items()):
            cond = None
            attr = Attr(key)
            if type_ == "=":
                cond = attr.eq(value)
            elif type_ == "<":
                cond = attr.lt(value)
            elif type_ == ">":
                cond = attr.lte(value)
            elif type_ == "{":
                cond = attr.is_in(value)
            elif type_ == "}":
                cond = attr.contains(value)
            if invert:
                cond = ~cond
            if overall_cond is None:
                overall_cond = cond
            else:
                overall_cond &= cond
        # Return async generator
        return db.scan_users(overall_cond, "via_instance, user_id")
