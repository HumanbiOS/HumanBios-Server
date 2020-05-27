from typing import TypedDict, List, Dict, Union, Set, Iterable
from translation import Translator
from settings import ROOT_PATH
from hashlib import sha1
from db import Database
import asyncio
import hashlib
import logging
import json
import os


def load(*path):
    path = os.path.join(ROOT_PATH, *path)
    with open(path) as strings:
        return json.load(strings)


class TextPromise:
    def __init__(self, key: str):
        self.key = key
        self.value = None
        self._format_data = None

    def fill(self, value):
        self.value: str = value

    def format(self, new_data) -> "TextPromise":
        self._format_data = new_data
        return self

    def __str__(self):
        if self._format_data is not None:
            self.value = self.value.format(self._format_data)
        return self.value


class StringAccessor:
    def __init__(self, lang: str, strings: "Strings"):
        self.lang = lang
        self.promises: Set[TextPromise] = set()
        self.strings = strings

    def __getitem__(self, key: str) -> TextPromise:
        promise = TextPromise(key)
        self.promises.add(promise)
        return promise

    async def fill_promises(self):
        translations = await self.strings.get_translations(self.lang, set(prom.key for prom in self.promises))
        for each_promise in self.promises:
            each_promise.fill(translations[each_promise.key])


class Strings:
    __strings = load('strings', 'json', 'strings.json')
    original_strings = {}
    for each_key in __strings:
        original_strings[each_key] = {
            "text": __strings[each_key],
            "hash": hashlib.sha1(__strings[each_key].encode()).hexdigest()
        }
    db = Database()
    cache = {'en': __strings}
    # Update english language

    def __init__(self, translation: Translator):
        self.tr = translation

    def __getitem__(self, key: str):
        return self.cache[key]

    async def get_translations(self, lang: str, keys: Iterable[str]) -> Dict[str, str]:
        # If original lang -> serve immediately
        if lang == "en":
            return {key: self.original_strings[key]["text"] for key in keys}
        # If present in cache -> return directly
        _cache = self.cache.get(lang)
        # if cache exists and contains all needed keys
        if _cache and all([key in _cache for key in keys]):
            return {key: _cache[key] for key in keys}
        # Otherwise check for cached in db
        _cached = await self.db.query_translations(lang, keys)
        if _cached and all([item is not None for item in _cached]):
            # Values with bad hashes
            _to_update = []
            # Result dict
            result = {}
            # Now verify that texts didn't change
            for each_translation in _cached:
                _key = each_translation['string_key']
                # If not accurate
                if each_translation['content_hash'] != self.original_strings[_key]['hash']:
                    _to_update.append(_key)
                else:
                    result[_key] = each_translation['text']
            # Update outdated text
            if _to_update:
                new_translations = await self.tr.translate_dict(
                    lang, {key: self.original_strings[key] for key in _to_update}
                )
                result.update(new_translations)
                # Save changes to db
                asyncio.ensure_future(self.db.bulk_save_translations(
                    [{'language': lang,
                      'string_key': key,
                      'content_hash': self.original_strings[key]['hash'],
                      'text': value} for key, value in result]
                ))
            # Save everything to cache
            if lang in self.cache:
                self.cache[lang].update(result)
            else:
                self.cache[lang] = result
            # Returning accurate result
            return result

        # Finally - working with brand new translations
        result = await self.tr.translate_dict(
            lang, {key: self.original_strings[key] for key in keys}
        )
        # Save everything to Database BUT not urgent
        asyncio.ensure_future(self.db.bulk_save_translations(
            [{'language': lang,
              'string_key': key,
              'content_hash': self.original_strings[key]['hash'],
              'text': value} for key, value in result]
        ))
        # Save everything to cache
        if lang in self.cache:
            self.cache[lang].update(result)
        else:
            self.cache[lang] = result
        return result
