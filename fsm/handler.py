from db import Database, User, BroadcastMessage, Session
from datetime import timedelta, datetime
from settings import settings, tokens
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


class Worker(threading.Thread):
    def __init__(self, loop_time=1.0 / 250):
        self.q = queue.Queue()
        self.timeout = loop_time
        self.handler = Handler()
        super(Worker, self).__init__()

    def process(self, ctx):
        self.q.put(ctx)

    async def _run_processes(self):
        while True:
            try:
                ctx = self.q.get(timeout=self.timeout)
                asyncio.ensure_future(self.handler.process(ctx))
            except queue.Empty:
                await self.idle()
            except Exception as e:
                logging.exception(e)

    def run(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        # Background tasks thread
        BackgroundTasks(self.handler).start()

        loop.run_until_complete(self._run_processes())

    async def idle(self):
        await asyncio.sleep(self.timeout)


class BackgroundTasks(threading.Thread):
    def __init__(self, handler: "Handler"):
        self.handler = handler
        super(BackgroundTasks, self).__init__()

    def run(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        # All tasks that should run
        asyncio.ensure_future(self.all_tasks())
        loop.run_forever()

    async def all_tasks(self):
        # Reminder loop
        asyncio.ensure_future(self.handler.reminder_loop())
        # Broadcast messages loop
        asyncio.ensure_future(self.handler.broadcast_loop())
        


class Handler(object):
    STATES_HISTORY_LENGTH = 10

    def __init__(self):
        self.__start_state = "StartState"
        self.__blogging_state = "BloggingState"
        self.__states = {}
        self.__register_states(*states.collect())
        self.db = Database()

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
            return False, self.__states[self.__start_state](), self.__start_state
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
                        "states": list(),
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

        await self.__register_event(user)
        return user

    async def __register_event(self, user: User):
        # TODO: REGISTER USER ACTIVITY
        pass

    async def process(self, context):
        # Getting or registering user
        user = await self.__get_or_register_user(context)
        # Finding last registered state of the user
        last_state = await self.last_state(user, context)
        # Looking for state, creating state object
        correct_state, current_state, current_state_name = self.__get_state(last_state)
        if not correct_state:
            user['states'].append(current_state_name)
            await self.db.commit_user(user)
        # Call process method of some state
        ret_code = await current_state.wrapped_process(context, user)
        await self.__handle_ret_code(context, user, ret_code)

    # get last state of the user
    async def last_state(self, user: User, context):
        # special cases #
        # TELEGRAM SPECIAL CASES
        if context['request']['service_in'] == ServiceTypes.TELEGRAM:
            text = context['request']['message']['text']
            if isinstance(text, str) or hasattr(text, "value"):
                text = str(text)
                if text.startswith("/start"):
                    context['request']['message']['text'] = text[6:].strip()
                    return self.__start_state
                if  text.startswith("/postme"):
                    return self.__blogging_state
        # defaults to __start_state
        try:
            return user['states'][-1]
        except IndexError:
            return self.__start_state

    async def __handle_ret_code(self, context, user, ret_code):
        # Handle return codes
        #    If status is OK -> Done
        #    If status is GO_TO_STATE -> proceed executing wanted state
        if ret_code == states.OK:
            return
        elif isinstance(ret_code, states.GO_TO_STATE):
            await self.__forward_to_state(context, user, ret_code.next_state)

    async def __forward_to_state(self, context, user, next_state):
        last_state = await self.last_state(user, context)
        correct_state, current_state, current_state_name = self.__get_state(next_state)
        # Registering new last state
        user['states'].append(current_state_name)
        await self.db.commit_user(user)
        # Check if history is too long
        if len(user['states']) > self.STATES_HISTORY_LENGTH:
            await self.db.update_user(user['identity'], "REMOVE states[0]", None, user)

        if current_state.has_entry:
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
