from typing import TypedDict, List, Dict, Union, Set, Iterable
from .items import TextPromise, Button
from translation import Translator
from settings import ROOT_PATH
import asyncio
import hashlib
import logging
import json
import os

def load(*path):
    path = os.path.join(ROOT_PATH, *path)
    with open(path) as strings:
        return json.load(strings)


class StringAccessor:
    def __init__(self, lang: str, strings: "Strings"):
        self.lang = lang
        self.promises: List[TextPromise] = list()
        self.strings = strings

    def __getitem__(self, key: str) -> TextPromise:
        promise = TextPromise(key)
        res = self.strings[self.lang].get(key)
        if res is None:
            self.promises.append(promise)
        else:
            promise.fill(res)
        return promise

    async def fill_promises(self):
        translations = await self.strings.get_translations(self.lang, list(prom.key for prom in self.promises))
        for each_promise in self.promises:
            each_promise.fill(translations[each_promise.key])


class Strings:
    __strings = load('strings', 'json', 'strings.json')
    if os.path.exists(os.path.join(ROOT_PATH, 'archive', 'latest.json')):
        for message in load('archive', 'latest.json'):
            __strings[message['text_key']] = message['text']
            if message['buttons']:
                for btn in message['buttons']:
                    __strings[btn['text_key']] = btn['text']

    original_strings = {}
    for each_key in __strings:
        original_strings[each_key] = {
            "text": __strings[each_key],
            "hash": hashlib.sha1(__strings[each_key].encode()).hexdigest()
        }
    cache = {'en': __strings}
    # Update english language

    def __init__(self, translation: Translator, db):
        self.tr = translation
        self.db = db
        asyncio.run(self.load_everything())
    
    def __getitem__(self, key: str):
        return self.cache.get(key, {})

    def update_strings(self):
        self.__strings = load('strings', 'json', 'strings.json')
        self.original_strings = {}

        for message in load('archive', 'latest.json'):
            self.__strings[message['text_key']] = message['text']
            if message['buttons']:
                for btn in message['buttons']:
                    self.__strings[btn['text_key']] = btn['text']
        
        for each_key in self.__strings:
            self.original_strings[each_key] = {
                "text": self.__strings[each_key],
                "hash": hashlib.sha1(self.__strings[each_key].encode()).hexdigest()
            }
        # make sure to update pointer
        self.cache['en'] = self.__strings

    def get(self, key: str):
        return self.cache.get(key)

    async def get_translations(self, lang: str, keys: Iterable[str]) -> Dict[str, str]:
        # If original lang -> serve immediately
        if lang == "en":
            return {key: self.original_strings[key]["text"] for key in keys}
        # If present in cache -> return directly
        _cache = self.cache.get(lang)
        _uncached_keys = list(keys)
        _cached_keys = list()
        if _cache:
            for key in keys:
                if key in _cache:
                    _cached_keys.append(key)
                    _uncached_keys.remove(key)
            RESULT = {key: _cache[key] for key in _cached_keys}
        else:
            RESULT = {}
        # if cache exists and contains all needed keys
        if not _uncached_keys:
            return RESULT
        # Otherwise check for cached in db
        _cached_db = await self.db.query_translations(lang, _uncached_keys)
        if _cached_db and all(_cached_db):
            # Values with bad hashes
            _to_update = []
            # Now verify that texts didn't change
            for each_translation in _cached_db:
                _key = each_translation['string_key']
                # If not accurate
                if each_translation['content_hash'] != self.original_strings[_key]['hash']:
                    _to_update.append(_key)
                else:
                    RESULT[_key] = each_translation['text']
            # Update outdated text
            if _to_update:
                new_translations = await self.tr.translate_dict(
                    lang, {key: self.original_strings[key]['text'] for key in _to_update}
                )
                RESULT.update(new_translations)
                # Save changes to db
                asyncio.ensure_future(self.db.bulk_save_translations(
                    [{'language': lang,
                      'string_key': key,
                      'content_hash': self.original_strings[key]['hash'],
                      'text': RESULT[key]} for key in RESULT]
                ))
            # Save everything to cache
            if lang in self.cache:
                self.cache[lang].update(RESULT)
            else:
                self.cache[lang] = RESULT
            # Returning accurate result
            return RESULT

        # Finally - working with brand new translations
        RESULT.update(await self.tr.translate_dict(
            lang, {key: self.original_strings[key]['text'] for key in _uncached_keys}
        ))
        # Save everything to Database BUT not urgent
        asyncio.ensure_future(self.db.bulk_save_translations(
            [{'language': lang,
              'string_key': key,
              'content_hash': self.original_strings[key]['hash'],
              'text': RESULT[key]} for key in RESULT]
        ))
        # Save everything to cache
        if lang in self.cache:
            self.cache[lang].update(RESULT)
        else:
            self.cache[lang] = RESULT
        return RESULT

    async def load_everything(self):
        count = 0
        async for each_translation in self.db.iter_all_translation():
            if self.cache.get(each_translation['language']):
                self.cache[each_translation['language']][each_translation['string_key']] = each_translation['text']
            else:
                self.cache[each_translation['language']] = {each_translation['string_key']: each_translation['text']}
            count += 1
        logging.info(f"Loaded {count} translated items from database.")
