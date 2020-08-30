from server_logic.definitions import Context
from settings import AI_URL
from . import base_state
from db.db import custom_default
from db import User
import aiohttp
import logging
import json


class AIState(base_state.BaseState):
    async def entry(self, context: Context, user: User, db):
        context['request']['message']['text'] = self.strings['ai_notice'] 
        context['request']['has_buttons'] = True
        context['request']['buttons'] = [{"text": self.strings['stop']}]
        self.send(user, context)
        return base_state.OK

    async def process(self, context: Context, user: User, db):
        # Alias for text answer
        raw_answer = context['request']['message']['text']
        # Parse button to have easy access to intent
        button = self.parse_button(raw_answer)
        if button == "stop":
            return base_state.GO_TO_STATE("ENDState")

        resp = await self.get_response(user['user_id'], raw_answer) 
        
        context['request']['message']['text'] = resp
        context['request']['has_buttons'] = True
        context['request']['buttons'] = [{"text": self.strings['stop']}]
        self.send(user, context)
        return base_state.OK

    async def get_response(self, user_id, prompt):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f"{AI_URL}/api/get_response",
                    json=json.dumps({"user_id": user_id, "text": prompt}, default=custom_default),
                    #headers={"Content-Type": "application/json"}
                ) as resp:
                    res = await resp.json()
                    logging.info(f"AI resp: {res}")
                    return res['text']

