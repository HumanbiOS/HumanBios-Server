from jsonschema import Draft7Validator, validators, ValidationError

from .serializable import Serializable
from settings import ROOT_PATH, tokens
from collections import namedtuple
from copy import copy, deepcopy
from . import UserIdentity
import json
import os


# Load schema method
def load(schema_path) -> dict:
    with open(schema_path) as schema_file:
        return json.load(schema_file)


# Method to extend validator behavior -> set defaults
def extend_with_default(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        for property_, sub_schema in properties.items():
            if "default" in sub_schema:
                instance.setdefault(property_, sub_schema["default"])
                if isinstance(property_, dict):
                    for sub_property_, sub_sub_schema in sub_schema["properties"]:
                        instance[property_][sub_property_] = sub_sub_schema["default"]

        for error in validate_properties(
            validator, properties, instance, schema,
        ):
            yield error

    context_checker = Draft7Validator.TYPE_CHECKER.redefine("Context", lambda _, inst: isinstance(inst, Context))

    return validators.extend(
        validator_class, {"properties": set_defaults}, type_checker=context_checker
    )


# The schema from file
SCHEMA = load(os.path.join(ROOT_PATH, 'server_logic', 'schema.json'))
# Validator with defaults
DefaultValidatingDraft7Validator = extend_with_default(Draft7Validator)
Validator = DefaultValidatingDraft7Validator(schema=SCHEMA)
ValidationResult = namedtuple("ValidationResult", ["validated", "object", "error"])


class Context(Serializable):
    @classmethod
    def from_json(cls, json_ish):
        validated = True
        try:
            # TODO: Disallow unfeatured properties?
            # TODO: Or it will be too resource-consuming?
            Validator.validate(json_ish)
            error = False
        except ValidationError as e:
            validated = False
            error = e.message
        if validated:
            obj = cls()
            # Set request value
            obj['request'] = json_ish
            # By default create user identity
            obj['request']['user']['identity'] = UserIdentity.hash(
                obj['request']['user']['user_id'],
                obj['request']['service_in']
            )
        else:
            obj = None
        return ValidationResult(validated, obj, error)

    def replace_security_token(self):
        # Make sure to pass correct token
        self['request']['security_token'] = tokens['server']

    def to_dict(self):
        return self.__dict__['request']

    def copy(self):
        return copy(self)

    def deepcopy(self):
        return deepcopy(self)

    @property
    def ok(self):
        return {"status": 200}
