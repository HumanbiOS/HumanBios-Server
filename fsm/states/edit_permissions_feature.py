from . import base_state
from server_logic.definitions import Context
from db import User
from db.enums import PermissionLevel
from settings import settings


class EditPermissionsState(base_state.BaseState):

    async def entry(self, context: Context, user: User, db):
        # Make sure to save previous state with fallback for the index error
        if user["identity"] != settings.OWNER_HASH:
            return base_state.GO_TO_STATE(user["states"][-2])  # exit with no action
        user["context"]["editing_permissions_state"] = user["states"][-2]

        # Explain usage of broadcast targets
        context['request']['message']['text'] = self.strings["edit_permissions_identity"]
        context['request']['buttons_type'] = "text"
        context['request']['has_buttons'] = True
        context['request']['buttons'] = [
             {"text": self.strings["back"]},
             {"text": self.strings["stop"]}
        ]
        # Don't forget to add task
        self.send(user, context)
        user["context"]["editing_permissions"] = "identity"
        return base_state.OK

    async def process(self, context: Context, user: User, db):
        if user["identity"] != settings.OWNER_HASH:
            # we should never get here, but it doesn't hurt to be careful
            return base_state.GO_TO_STATE("ENDState")

        text = context["request"]["message"]["text"]
        button = self.parse_button(text)

        if button == "stop":
            return base_state.GO_TO_STATE("ENDState")
        elif button == "back":
            prev = user["context"]["editing_permissions_state"]
            del user["context"]["editing_permissions_state"]
            return base_state.GO_TO_STATE(prev)
        elif user["context"]["editing_permissions"] == "identity":
            user["context"]["editing_permissions_identity"] = text.strip()
            user["context"]["editing_permissions"] = "action"
            await self._list_actions(context, user)
            return base_state.OK
        elif user["context"]["editing_permissions"] == "action":
            level = {
                "default": PermissionLevel.DEFAULT,
                "broadcaster": PermissionLevel.BROADCASTER,
                "admin": PermissionLevel.ADMIN
            }.get(button, None)
            if level is None:
                await self._list_actions(context, user)
                return base_state.OK
            if user["context"]["editing_permissions_identity"] in ("me", user["identity"]):
                # fsm always commits after the process, so we have to do this seperately
                user["permission_level"] = level
            else:
                await db.update_user(
                    user["context"]["editing_permissions_identity"],
                    "SET permission_level = :v",
                    {":v": level}
                )
            del user["context"]["editing_permissions"]
            prev = user["context"]["editing_permissions_state"]
            del user["context"]["editing_permissions_state"]
            return base_state.GO_TO_STATE(prev)

    async def _list_actions(self, context: Context, user: User):
        context['request']['message']['text'] = self.strings["edit_permissions_action"]
        context['request']['buttons_type'] = "text"
        context['request']['has_buttons'] = True
        context['request']['buttons'] = [
            {"text": self.strings["default"]},
            {"text": self.strings["broadcaster"]},
            {"text": self.strings["admin"]},
            {"text": self.strings["back"]},
            {"text": self.strings["stop"]}
        ]
        # Don't forget to add task
        self.send(user, context)
