from server_logic.definitions import Context
from db import User
from . import base_state
import iso639
import logging


class LanguageDetectionState(base_state.BaseState):

    async def entry(self, context: Context, user: User, db):
        user['context']['bq_state'] = 1
        # Special case for telegram-like client side language code entity
        if user['context'].get('language_state') is None and context['request']['user']['lang_code']:
            lang = iso639.find(context['request']['user']['lang_code'])
            if lang and lang['name'] != "Undetermined":
                # Update current context
                user['language'] = lang['iso639_1']
                self.set_language(lang['iso639_1'])

                # Ask if user wants to continue with the language
                context['request']['message']['text'] = self.strings["app_confirm_language"].format(lang['native'])
                context['request']['has_buttons'] = True
                context['request']['buttons_type'] = "text"
                context['request']['buttons'] = [
                    {"text": self.strings['yes']},
                    {"text": self.strings['no']},
                    {"text": self.strings['stop']}
                ]

                user['context']['language_state'] = 4
                self.send(user, context)
                # [DEBUG]
                # logging.info(f"{user['context']['language_state']}, {user['language']}")
                return base_state.OK
            # [DEBUG]
            # logging.info(f"{lang}, {context['request']['user']['lang_code']}")

        # Send language message
        context['request']['message']['text'] = self.strings["choose_lang"]
        # Add confirmation button to skip
        if context['request']['user']['lang_code']:
            user['context']['lang_code'] = context['request']['user']['lang_code']
            context['request']['has_buttons'] = True
            context['request']['buttons_type'] = "text"
            context['request']['buttons'] = [
                {"text": self.strings['skip_lang'].format(context['request']['user']['lang_code'])}
            ]
        # Set user context as 'Was Asked Language Question'
        user['context']['language_state'] = 1
        # Don't forget to add task
        self.send(user, context)
        return base_state.OK

    async def process(self, context: Context, user: User, db):
        raw_answer = context['request']['message']['text']
        failed = True
        button = self.parse_button(raw_answer)
        # [DEBUG]
        # logging.info(f"Button key: {button.key}")

        if button == 'stop':
            # Jump from current state to final `end` state
            return base_state.GO_TO_STATE("ENDState")

        if user['context'].get('language_state') == 1:
            # Autodetection button
            if self.parse_fstring(raw_answer, self.strings['skip_lang']):
                # Use current lang, if none -> use from cache
                #    (May make sense if some front end sends lang data only once on first request)
                if context['request']['user']['lang_code']:
                    lang = context['request']['user']['lang_code']
                else:
                    lang = user['context']['lang_code']
                
                user['language'] = context['request']['user']['lang_code']
                self.set_language(context['request']['user']['lang_code'])
                return base_state.GO_TO_STATE("QAState")
            # Run language detection
            language_obj = await self.nlu.detect_language(raw_answer)
            # Couldn't detect any language
            if language_obj is None:
                # Ask if user wants to continue with the language
                context['request']['message']['text'] = self.strings["failed_language"].format(raw_answer)
                context['request']['has_buttons'] = True
                context['request']['buttons_type'] = "text"
                context['request']['buttons'] = [
                    {"text": self.strings['stop']}
                ]
                self.send(user, context)
                return base_state.OK

            if isinstance(language_obj, list) and len(language_obj) != 1:
                user['context']['language_state'] = 3
                user['context']['language_obj'] = {lang['native']: lang['iso639_1'] for lang in language_obj}
                # Ask what language user wants
                context['request']['message']['text'] = self.strings['choose_lang_country_based']
                context['request']['has_buttons'] = True
                context['request']['buttons_type'] = "text"
                context['request']['buttons'] = [
                    *({"text": lang['native']} for lang in language_obj),
                    {"text": self.strings['stop']},
                    {"text": self.strings['try_again']}
                ]
                self.send(user, context)
                return base_state.OK
            elif isinstance(language_obj, list):
                language_obj = language_obj[0]

            # Update current context
            user['language'] = language_obj['iso639_1']
            self.set_language(language_obj['iso639_1'])

            # Ask if user wants to continue with the language
            context['request']['message']['text'] = self.strings["confirm_language"].format(language_obj['native'])
            context['request']['has_buttons'] = True
            context['request']['buttons_type'] = "text"
            context['request']['buttons'] = [
                {"text": self.strings['continue']},
                {"text": self.strings['try_again']},
                {"text": self.strings['stop']}
            ]
            user['context']['language_state'] = 2
            self.send(user, context)
            return base_state.OK

        elif user['context'].get('language_state') == 2:
            if button == 'continue':
                return base_state.GO_TO_STATE("QAState")
            elif button == 'try_again':
                failed = False
                user['language'] = 'en'
                self.set_language('en')

        elif user['context'].get('language_state') == 3:
            lang = user['context']['language_obj'].get(raw_answer)
            if lang is not None:
                user['language'] = lang
                return base_state.GO_TO_STATE("QAState")
            elif button == 'try_again':
                failed = False

        elif user['context'].get('language_state') == 4:
            if button == 'yes':
                # [DEBUG]
                # logging.info("Returing to the Basic Question State.")
                return base_state.GO_TO_STATE("QAState")
            elif button == 'no':
                failed = False

        if failed:
            # Failed to recognise the answer -> fail message path
            context['request']['message']['text'] = self.strings["invalid_answer"]
            self.send(user, context)
        # Send language message, but now with "Stop" button
        context['request']['message']['text'] = self.strings["choose_lang"]
        context['request']['has_buttons'] = True
        context['request']['buttons_type'] = "text"
        context['request']['buttons'] = [
            {"text": self.strings['stop']}
        ]
        # Set user context as 'Was Asked Language Question'
        user['context']['language_state'] = 1
        # Don't forget to add task
        self.send(user, context)
        return base_state.OK
