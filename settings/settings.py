import logging
import pathlib
import dotenv
import os
import ast

dotenv.load_dotenv('.env')

ROOT_PATH = pathlib.Path(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

SERVER_SECURITY_TOKEN = os.environ['SERVER_SECURITY_TOKEN']

CLOUD_TRANSLATION_API_KEY = os.environ['CLOUD_TRANSLATION_API_KEY']

AI_URL = os.environ['AI_URL']
DATABASE_URL = os.environ['DATABASE_URL']
STATIC_URL = os.environ['STATIC_URL']

AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']

RASA_URL = os.environ['RASA_URL']
BOTSOCIETY_API_KEY = os.environ['BOTSOCIETY_API_KEY']

N_CORES = int(os.environ['N_CORES'])
try:
    DEBUG = bool(ast.literal_eval(os.environ['DEBUG']))
except (ValueError, SyntaxError) as e:
    DEBUG = None
    logging.exception(f"Expected bool, got {os.environ['DEBUG']}")

OWNER_HASH = os.environ.get("OWNER_HASH", None)
