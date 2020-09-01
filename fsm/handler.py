from db import Database, User, BroadcastMessage, Session
from datetime import timedelta, datetime
from db.enums import PermissionLevel
from settings import settings, tokens, ROOT_PATH
from fsm.states.base_state import BaseState
import fsm.states as states
from db import ServiceTypes
from db import CheckBack
from typing import List
import threading
import asyncio
import aiohttp
import logging
import random
import queue
import json
import os


class Worker(threading.Thread):
    def __init__(self, loop_time=1.0 / 250):
        self.q = queue.Queue()
        self.random_q = queue.Queue()
        self.timeout = loop_time
        self.handler = Handler()
        super(Worker, self).__init__()

    def process(self, ctx):
        self.q.put(ctx)

    async def _run_processes(self):
        # # # Background tasks # # #
        # Reminder loop
        asyncio.ensure_future(self.handler.reminder_loop())
        # Broadcast messages loop
        asyncio.ensure_future(self.handler.broadcast_loop())
        # Loop of updating botsociety file data for the core path 
        asyncio.ensure_future(self.autoload_file())

        while True:
            try:
                ctx = self.q.get(timeout=self.timeout)
                asyncio.ensure_future(self.handler.process(ctx))
            except queue.Empty:
                await self.idle()
            except Exception as e:
                logging.exception(e)

    async def idle(self):
        await asyncio.sleep(0)

    def run(self):
        asyncio.run(self._run_processes())

    # @Important: async infinite task to propagate update on webhook to handler's thread
    async def autoload_file(self):
        while True:
            try:
                self.random_q.get(timeout=1.0/250)
                self.handler.load_bots_file()
            except queue.Empty:
                await asyncio.sleep(1)
            except Exception as e:
                logging.exception(e)
    
    def reload_file(self):
        self.random_q.put(True)
        

class Handler(object):
    STATES_HISTORY_LENGTH = 10
    START_STATE = "StartState"
    BLOGGING_STATE = "BloggingState"
    BROADCASTING_STATE = "BroadcastingState"
    GET_ID_STATE = "GetIdState"
    EDIT_PERMISSIONS_STATE = "EditPermissionsState"
    latest_data_fp = os.path.join(ROOT_PATH, "archive", "latest.json") 

    def __init__(self):
        self.__states = {}
        self.__register_states(*states.collect())
        self.db = Database()

        if os.path.exists(self.latest_data_fp):
            self.load_bots_file()
            logging.info("Succesfuly loaded Core Botsociety file.")
        else:
            BaseState.bots_data = None
            logging.warning("No Core Botsociety file was found!")

    def __register_state(self, state_class):
        self.__states[state_class.__name__] = state_class

    def __register_states(self, *states_):
        for state in states_:
            self.__register_state(state)

    def __get_state(self, name):
        if callable(name):
            name = name.__name__
        state = self.__states.get(name)
        if state is None:
            # If non-existing state - send user to the start state
            # @Important: Don't forget to initialize the state
            return False, self.__states[Handler.START_STATE](), Handler.START_STATE
        # @Important: Don't forget to initialize the state
        return True, state(), name

    async def __get_or_register_user(self, context):
        # Getting user from database
        user = await self.db.get_user(context['request']['user']['identity'])
        if user is None:
            user = {
                "user_id": context['request']['user']['user_id'],
                "service": context['request']['service_in'],
                "identity": context['request']['user']['identity'],
                "via_instance": context['request']['via_instance'],
                "first_name": context['request']['user']['first_name'],
                "last_name": context['request']['user']['last_name'],
                "username": context['request']['user']['username'],
                "language": 'en',
                "type": self.db.types.COMMON,
                "created_at": self.db.now().isoformat(),
                "last_location": None,
                "last_active": self.db.now().isoformat(),
                "conversation_id": None,
                "answers": dict(),
                "files": dict(),
                "states": list("ENDState"),
                "permission_level": PermissionLevel.DEFAULT, 
                "context": dict()
            }
            await self.db.create_user(user)

        # @Important: Dynamically update associated service instance, when it was changed
        if context['request']['via_instance'] != user["via_instance"]:
            # Update database
            user = await self.db.update_user(
                user['identity'],
                "SET via_instance = :v",
                {":v": context['request']['via_instance']},
                user
            )

        #await self.__register_event(user)
        return user

    #async def __register_event(self, user: User):
    #    # TODO: REGISTER USER ACTIVITY
    #    pass

    async def process(self, context):
        # Getting or registering user
        user = await self.__get_or_register_user(context)
        # Finding last registered state of the user
        special_state = await self.get_command_state(user, context)
        if special_state:
            await self.__forward_to_state(context, user, special_state)
            return
        last_state = await self.last_state(user, context)
        # Looking for state, creating state object
        correct_state, current_state, current_state_name = self.__get_state(last_state)
        if not correct_state:
            user['states'].append(current_state_name)
            # @Important: maybe we don't need to commit, since we will commit after?
            # await self.db.commit_user(user)
        # Call process method of some state
        ret_code = await current_state.wrapped_process(context, user)
        await self.__handle_ret_code(context, user, ret_code)


    async def get_command_state(self, user: User, context):
        text = context['request']['message']['text']
        if isinstance(text, str) or hasattr(text, "value"):
            text = str(text)
            if text.startswith("/start"):
                context['request']['message']['text'] = text[6:].strip()
                return Handler.START_STATE
            if text.startswith("/postme"):
                return Handler.BLOGGING_STATE
            if text.startswith("/broadcast"):
                return Handler.BROADCASTING_STATE
            if text.startswith("/id"):
                return Handler.GET_ID_STATE
            if text.startswith("/edit_permissions"):
                return Handler.EDIT_PERMISSIONS_STATE


    # get last state of the user
    async def last_state(self, user: User, context):
        # defaults to START_STATE
        try:
            return user['states'][-1]
        except IndexError:
            pass
        except KeyError:
            user['states'] = ["ENDState"]
        return Handler.START_STATE

    async def __handle_ret_code(self, context, user, ret_code):
        # Handle return codes
        #    If status is OK -> Done
        #    If status is GO_TO_STATE -> proceed executing wanted state
        if not ret_code.process_next:
            return
        elif isinstance(ret_code, states.GO_TO_STATE):
            await self.__forward_to_state(context, user, ret_code.next_state, entry=ret_code.entry)
        elif ret_code == states.END:
            user['states'].pop()
            await self.__forward_to_state(context, user, user['states'][-1], entry=ret_code.entry)

    async def __forward_to_state(self, context, user, next_state, entry=False):
        last_state = await self.last_state(user, context)
        correct_state, current_state, current_state_name = self.__get_state(next_state)
        if current_state_name != last_state:
            # Registering new last state
            user['states'].append(current_state_name)
            # @Important: maybe we don't need to commit, since we will commit after?
            # await self.db.commit_user(user)
            # Check if history is too long
            if len(user['states']) > self.STATES_HISTORY_LENGTH:
                # @Important: maybe we don't need to update, since we will commit after?
                # await self.db.update_user(user['identity'], "REMOVE states[0]", None, user)
                user['states'].pop(0)
        if current_state.has_entry and (current_state_name != last_state or entry):
            ret_code = await current_state.wrapped_entry(context, user)
        else:
            ret_code = await current_state.wrapped_process(context, user)
        await self.__handle_ret_code(context, user, ret_code)

    async def reminder_loop(self) -> None:
        try:
            logging.info("Reminder loop started")
            while True:
                now = self.db.now()
                #next_circle = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
                next_circle = (now + timedelta(seconds=10)).replace(microsecond=0)
                await asyncio.sleep((next_circle - now).total_seconds())
                await self.schedule_nearby_reminders(next_circle)
        except asyncio.CancelledError:
            logging.info("Reminder loop stopped")
        except Exception as e:
            logging.exception(f"Exception in reminder loop: {e}")

    async def schedule_nearby_reminders(self, now: datetime) -> None:
        #until = now + timedelta(minutes=1)
        until = now + timedelta(seconds=10)
        count, all_items_in_range = await self.db.all_checkbacks_in_range(now, until)
        # Send broadcast in the next minute, but not all at the same time
        send_at_list = [(60 / count) * i for i in range(count)]
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(*[self.send_reminder(send_at, checkback, session)
                                   for send_at, checkback in zip(send_at_list, all_items_in_range)])

    async def send_reminder(self, send_at: float, checkback: CheckBack, session: aiohttp.ClientSession) -> None:
        try:
            logging.info(f"Sending checkback after {send_at} seconds")
            await asyncio.sleep(send_at)
            logging.info("Sending checkback")
            await self._send_reminder(checkback, session)
        except Exception as e:
            logging.exception(f"Failed to send reminder: {e}")

    async def _send_reminder(self, reminder: CheckBack, session: aiohttp.ClientSession) -> None:
        await self.db.update_user(
            reminder['identity'],
            "SET states = list_append(states, :i)",
            {":i": ["CheckbackState"]}
        )
        context = json.loads(reminder["context"])
        url = tokens[context['via_instance']].url
        # TODO: Find a better way to deal with decimals
        async with session.post(url, json=context) as response:
            # If reached server - log response
            if response.status == 200:
                result = await response.json()
                logging.info(f"Sending checkback status: {result}")
                return result
            # Otherwise - log error
            else:
                logging.error(f"[ERROR]: Sending checkback (send_at={reminder['send_at']}, "
                              f"identity={reminder['identity']}) status {await response.text()}")

    async def broadcast_loop(self) -> None:
        try:
            logging.info("Broadcast loop started")
            while True:
                now = self.db.now()
                next_circle = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
                await asyncio.sleep((next_circle - now).total_seconds())
                await self.schedule_broadcasts()
        except asyncio.CancelledError:
            logging.info("Broadcasts loop stopped")
        except Exception as e:
            logging.exception(f"Exception in broadcasts loop: {e}")

    async def schedule_broadcasts(self):
        count, all_items_in_range = await self.db.all_new_broadcasts()
        # will raise ZeroDivisionError
        if count == 0:
            return
        all_frontend_sessions = await self.db.all_frontend_sessions()
        # Nowhere to send
        if not all_frontend_sessions:
            return
        async with aiohttp.ClientSession() as session:
            # Send broadcast in the next minute, but not all at the same time
            send_at_list = [(60 / count) * i for i in range(count)]
            await asyncio.gather(
                *[
                    self.send_broadcast(send_at, message, all_frontend_sessions, session)
                    for send_at, message in
                    zip(send_at_list, all_items_in_range)
                ]
            )

    async def send_broadcast(self,
                             send_at: float,
                             broadcast_message: BroadcastMessage,
                             frontend: List[Session],
                             session: aiohttp.ClientSession):
        await asyncio.sleep(send_at)
        context = json.loads(broadcast_message["context"])
        tasks = list()
        for each_session in frontend:
            context['chat']['chat_id'] = each_session['broadcast']
            tasks.append(session.post(each_session['url'], json=context))
        await asyncio.gather(*tasks)
        # Remove done broadcast task
        await self.db.remove_broadcast(broadcast_message)

    @classmethod
    def load_bots_file(cls):
        with open(os.path.join(ROOT_PATH, "archive", "latest.json")) as source:
            BaseState.bots_data = json.load(source)
            BaseState.STRINGS.update_strings()
