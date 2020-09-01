from fsm.states.base_state import BaseState, OK, GO_TO_STATE, END
import importlib
import inspect
import os


def collect():
    collection = list()
    # For all files in current folder
    for file in os.listdir(os.path.dirname(__file__)):
        # If file starts from letter and ends with .py
        if file[0].isalpha() and file.endswith('.py'):
            # Name of the file with prefix "states." but without ".py"
            name_as_module = f'{__name__}.{file[:-3]}'
            # Import this file
            as_module = importlib.import_module('.', name_as_module)
            # For each object definition that is a class
            for name, obj in inspect.getmembers(as_module, inspect.isclass):
                # If class is a subclass of BaseState, but not BaseState itself [Redundant?]
                if issubclass(obj, BaseState) and obj != BaseState:
                    collection.append(obj)
    return collection
