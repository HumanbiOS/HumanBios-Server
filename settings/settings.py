import dotenv
import os
dotenv.load_dotenv('.env')

ROOT_PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

SERVER_SECURITY_TOKEN = os.environ['SERVER_SECURITY_TOKEN']

CLOUD_TRANSLATION_API_KEY = os.environ['CLOUD_TRANSLATION_API_KEY']
