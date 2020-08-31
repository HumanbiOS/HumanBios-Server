from . import base_state
from server_logic.definitions import Context
from db import User
from settings import DEBUG, SERVER_HOST, SERVER_PORT, OWNER_HASH
from urllib.parse import urlunparse


class WebAdminLoginState(base_state.BaseState):
    has_entry = False

    async def process(self, context: Context, user: User, db):
        if user["identity"] != OWNER_HASH and user["permission_level"] == PermissionLevel.DEFAULT:
            return base_state.GO_TO_STATE(user["states"][-2])
        scheme = "http" if DEBUG else "https"
        token = await db.create_webtoken(user["identity"])
        url = urlunparse((scheme, SERVER_HOST + ":" + str(SERVER_PORT), "/admin/auth/" + token, None, None, None))
        context['request']['message']['text'] = self.strings["webtoken"].format(url)
        self.send(user, context)
        return base_state.GO_TO_STATE(user['states'][-2])
