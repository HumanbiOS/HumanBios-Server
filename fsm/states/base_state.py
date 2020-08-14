from server_logic.definitions import Context, SenderTask, ExecutionTask
from strings import Strings, StringAccessor, TextPromise, Button
from settings import tokens, ROOT_PATH
from server_logic import NLUWorker
from translation import Translator
from aiohttp import ClientSession
from db import User, Database
from typing import Union, Optional
import aiofiles
import asyncio
import logging
import copy
import json
import os


class OK:
    status = 1
    commit = True

    def __init__(self, commit=True):
        self.commit = commit

    def __eq__(self, other):
        return self.status == other.status


class GO_TO_STATE:
    status = 2
    next_state = None
    commit = True

    def __init__(self, next_state, commit=True):
        self.next_state = next_state
        self.commit = commit

    def __eq__(self, other):
        return self.status == other.status


class PromisesEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, TextPromise):
            return str(o)
        return json.JSONEncoder.default(self, o)


class BaseState(object):
    """
    This class is a parent-class for all state handlers, it provides:
        - interface to Google Translations API
        - interface to our own phrases/responses
        - automatically translates our strings to the language of the user
        - automatically adds pictures to the chosen intents/conversation steps/questions
        - interface to the database
        - interface to the NLU (Natural Language Understanding unit - https://github.com/HumanbiOS/rasa)
        - automatic requests queueing
        - automatic database updates for the `User` object

    Note 0:
        In the text there are some special words:
          $(name) - refers to the random meaningful (or not) string that came to your mind
          $(root) - refers to the project directory
    Note 1:
        Server will pick up files and extract state classes from them, you don't need
        to worry about "registering state", there is no hardcoded list
        The important detail is that you **must** put state.py with the state handler
        to the $(root)/fsm/states folder.
    Note 2:
        It's a better practise to put each state handler in its own file.
        Naming Conventions:
            - name of the python class - `$(name)State`
              Example:
              `    class MyBeautifulState:`
              `    class BasicQuestionsState:`
            - name of the file - *snake lower case* of $(name).
              "state" might be omitted (filename matters only to avoid confusions, refer to note 1)
              Example:
              `my_beautiful_state.py`
              `basic_questions.py`
    """
    HEADERS = {
        "Content-Type": "application/json"
    }
    # This variable allows to ignore `entry()` when needed
    has_entry = True
    # @Important: instantiate important classes
    tr = Translator()
    db = Database()
    nlu = NLUWorker(tr)
    STRINGS = Strings(tr, db)
    
    bots_data = None

    # Media path and folder
    media_folder = "media"
    media_path = os.path.join(ROOT_PATH, media_folder)

    if not os.path.exists(media_path):
        os.mkdir(media_path)

    # Prepare state
    def __init__(self):
        # Keeps list of tasks
        self.tasks = list()
        # Keeps execution queue
        self.execution_queue = list()
        # Create language variable
        self.__language = None
        self.strings = None

    def set_language(self, value: str):
        """
        This method sets language to a current state
        If language is None - base language version is english

        Args:
            value (str): language code of the user's country
        """
        self.__language = value or "en"
        self.strings = StringAccessor(self.__language, self.STRINGS)

    async def wrapped_entry(self, context: Context, user: User):
        # Set language
        self.set_language(user['language'])
        # Wrap base method to avoid breaking server
        try:
            # Execute state method
            status = await self.entry(context, user, self.db)
        except Exception as e:
            # Do not commit to database if something went wrong
            status = OK(commit=False)
            # Log exception
            logging.exception(e)
        # Commit changes to database
        if status.commit:
            await self.db.commit_user(user=user)
        # @Important: Fulfill text promises
        if self.strings.promises:
            await self.strings.fill_promises()
        # @Important: Since we call this always, check if
        # @Important: the call is actually needed
        if self.tasks:
            # @Important: collect all requests
            _results = await self._collect()
        # @Important: Execute all queued jobs
        if self.execution_queue:
            await self._execute_tasks()
        return status

    async def wrapped_process(self, context: Context, user: User):
        # Set language
        self.set_language(user['language'])
        # Wrap base method to avoid breaking server
        try:
            # Execute state method
            status = await self.process(context, user, self.db)
        except Exception as e:
            # Do not commit to database if something went wrong
            status = OK(commit=False)
            # Log exception
            logging.exception(e)
        # Commit changes to database
        if status.commit:
            await self.db.commit_user(user=user)
        # @Important: Fulfill text promises
        if self.strings.promises:
            await self.strings.fill_promises()
        # @Important: Since we call this always, check if
        # @Important: the call is actually needed
        if self.tasks:
            # @Important: collect all requests
            await self._collect()
        # @Important: Execute all queued jobs
        if self.execution_queue:
            await self._execute_tasks()
        return status

    # Actual state method to be written for the state
    async def entry(self, context: Context, user: User, db):
        """
        The method handles each interaction when user enters your state

        Args:
        context (Context): language code of the user's country
        user (User): user object from database corresponding to the user who sent message
        db (Database): database wrapper object
        """
        return OK

    # Actual state method to be written for the state
    async def process(self, context: Context, user: User, db):
        """
        The method handles each interaction with user (except first interaction)

        Args:
        context (Context): language code of the user's country
        user (User): user object from database corresponding to the user who sent message
        db (Database): database wrapper object
        """
        return OK

    def parse_button(self, raw_text: str, truncated=False, truncation_size=20, verify=None) -> Button:
        """
        Function compares input text to all available strings (of user's language) and if
        finds matching - returns Button object, which has text and key attributes, where
        text is raw_text and key is a key of matched string from strings.json

        Args:
        raw_text (str): just user's message
        truncated (bool): option to look for not full matches (only first `n` characters). Defaults to False.
        truncation_size (int): amount of sequential characters to match. Defaults to 20.
        """
        # @Question: is it worth it?
        #    Optimise search if `verify` is not None, makes following loop O(n1) instead of O(n) where n1 is length of the verify, 
        #    which is 100% definitely in range 1-10
        btn = Button(raw_text)
        lang_obj = self.STRINGS.cache.get(self.__language)
        # Make sure that certain language file exists
        if lang_obj and verify:
            lang_obj = [(key, lang_obj[key]) for key in verify]
        elif lang_obj:
            lang_obj = lang_obj.items()

        for k, v in lang_obj:
            if v == raw_text or (truncated and len(v) > truncation_size and v[:truncation_size] == raw_text[:truncation_size]):
                # [DEBUG]
                # logging.info(value)
                btn.set_key(k)
                break
        # [DEBUG]
        # logging.info("\n\n\n\n")
        # logging.info(verify)
        # logging.info(lang_obj)
        # logging.info(btn)
        return btn

    # Parse intent of single-formatted string, comparing everything but inserted 
    #     Returns True           ->     intent matched
    #     Returns None or False  ->     intent didn't match
    def parse_fstring(self, raw_text: str, promise: TextPromise, item1: str = "{", item2: str = "}"):
        if promise.value and isinstance(promise.value, str):
            # Find where "{" or "}" should've been, then use it to go one char left or right, accordingly
            i1 = promise.value.find(item1)
            i2 = promise.value.find(item2)
            if i1 != -1 and i2 != -1:
                # Find from the end, so can use negative index
                #    Can't just measure from the start, because there will be inserted text of random length
                i2 = len(promise.value) - i2 
                return raw_text[:i1] == promise.value[:i1] and raw_text[-i2 + 1:] == promise.value[-i2 + 1:]


    # @Important: 1) find better way with database
    # @Important: 2) What if we do it in non blocking asyncio.create_task (?)
    # @Important:    But on the other hand, we can't relay on the file status
    # @Important:    for example if next call needs to upload it somewhere
    # @Important:    If you deal with reliability and consistency - great optimisation
    async def download_by_url(self, url, *folders, filename):
        # Make sure file exists
        if not self.exists(*folders):
            # Create folder on the path
            os.mkdir(os.path.join(self.media_path, *folders))
        # Full file path with filename
        filepath = os.path.join(self.media_path, *folders, filename)
        # Initiate aiohttp sessions, get file
        async with ClientSession() as session:
            async with session.get(url) as response:
                # Open file with aiofiles and start steaming bytes, write to the file
                logging.debug(f"Downloading file: {url} to {filepath}")
                async with aiofiles.open(filepath, 'wb') as f:
                    async for chunk in response.content.iter_any():
                        await f.write(chunk)
                logging.debug(f"Finished download [{filepath}]")
        return filepath

    # @Important: check if downloaded file exist
    def exists(self, *args):
        return os.path.exists(os.path.join(self.media_path, *args))

    # @Important: high level access to translation module
    # @Important: note, though, that we shouldn't abuse translation api
    # @Important: because a) it's not good enough, b) it takes time to make
    # @Important: a call to the google cloud api
    async def translate(self, text: str, target: str) -> str:
        """
        Method is wrapper for translation_text from translation module.
        Simply returns translated text for the target language.
        Good usage example if translating text between users.

        Args:
        text (str): message to translate
        target (str): target language (ISO 639-1 code)
        """
        return await self.tr.translate_text(text, target)

    # Sugar

    # @Important: command to actually send all collected requests from `process` or `entry`
    async def _collect(self):
        results = list()
        async with ClientSession(json_serialize=lambda o: json.dumps(o, cls=PromisesEncoder)) as session:
            # @Important: Since asyncio.gather order is not preserved, we don't want to run them concurrently
            # tasks = [self._send(task, session) for task in self.tasks[id(context)]]
            # group = asyncio.gather(*tasks)
            # results = await group
            # return results
            for each_task in self.tasks:
                res = await self._send(each_task, session)
                results.append(res)
        return results

    # @Important: Real send method, takes SenderTask as argument
    async def _send(self, task: SenderTask, session: ClientSession):
        # Takes instance data holder object with the name from the tokens storage, extracts url
        url = tokens[task.service].url
        # Unpack context, set headers (content-type: json)
        async with session.post(url,
                json=task.context,
                headers=self.HEADERS
            ) as resp:
            # If reached server - log response
            if resp.status == 200:
                pass  # [DEBUG]
                #result = await resp.json()
                #if result:
                #    logging.info(f"Sending task status: {result}")
                #    return result
                #else:
                #    logging.info(f"Sending task status: No result")
            # Otherwise - log error
            else:
                logging.error(f"[ERROR]: Sending task (service={task.service}, context={task.context}) status {await resp.text()}")

    # @Important: `send` METHOD THAT ALLOWS TO SEND PAYLOAD TO THE USER
    def send(self, to_entity: Union[User, str], context: Context):
        """
        Method creates task that sends context['request'] to the
        to_user User after executing your code inside state.

        Args:
        to_entity (User, str): user object to send message to, or just service name
        context (Context): request context that is send to the user. The object is deep copied so it
                           can't be changed further in code (reliable consistency for multiple requests)
        """
        # @Important: [Explanation to the code below]:
        # @Important: maybe add some queue of coroutines and dispatch them all when handler return status (?)
        # @Important: or just dispatch them via asyncio.create_task so it will be more efficient (?)
        # @Important: reasoning:
        # @Important:   simple way:   server -> request1 -> status1 -> request2 -> status2 -> request3 -> status3
        # @Important:     this way:   server -> gather(request1, request2, request3) -> log(status1, status2, status3)

        if isinstance(to_entity, str):
            service = to_entity
        else:
            service = to_entity['via_instance']

        self.tasks.append(SenderTask(service, copy.deepcopy(context.__dict__['request'])))

    async def _execute_tasks(self):
        results = await asyncio.gather(
            *[exec_task.func(*exec_task.args, **exec_task.kwargs) for exec_task in self.execution_queue]
        )
        return results

    def create_task(self, func, *args, **kwargs):
        """
        Method executes async function (with given args and kwargs) immediately after processing state.

        Args:
        func (Async Func): function to be executed
        args (Any): args to be passed into the func
        kwargs (Any): kwargs to be passed into the func
        """
        self.execution_queue.append(ExecutionTask(func, args, kwargs))

    def create_conversation(self, user1: User, user2: User, context: Context, message: Optional[str] = None) -> None:
        user1['context']['conversation'] = {
            "user_id": user2['user_id'],
            "via_instance": user2['via_instance'],
            "type": user2['type']
        }
        user2['context']['conversation'] = {
            "user_id": user1['user_id'],
            "via_instance": user1['via_instance'],
            "type": user1['type']
        }

        # Send message to them
        if message or message is None:
            if message is None:
                message = "You've just started realtime conversation. Just start typing to talk to them!"

            context['request']['user']['user_id'] = 1
            context['request']['user']['first_name'] = "HumanBios"
            context['request']['chat']['chat_id'] = user1['user_id']
            context['request']['message']['text'] = message
            self.send(user1, context)
            context['request']['chat']['chat_id'] = user2['user_id']
            self.send(user2, context)

        user1['states'].append("ConversationState")
        user2['states'].append("ConversationState")
