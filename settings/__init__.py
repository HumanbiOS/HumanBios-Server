from . import settings
from .settings import *
from collections import namedtuple as namedtuple
import logging
import os


Config = namedtuple("Config", ['token', 'url'])


tokens = {
    'server': SERVER_SECURITY_TOKEN,
    # Bot for tests, don't touch
    'tests_dummy_bot': Config('TEST_BOT_1111', 'http://dummy_url'),
}

__all__ = settings.__all__.copy() + ["Config", "tokens"]


# Logging
logdir = os.path.join(ROOT_PATH, 'log')
logfile = os.path.join(logdir, 'server.log')
if not os.path.exists(logdir):
    os.mkdir(logdir)
formatter = '%(asctime)s - %(filename)s - %(levelname)s - %(message)s'
date_format = '%d-%b-%y %H:%M:%S'

logging.basicConfig(
    format=formatter,
    datefmt=date_format,
    level=logging.INFO
)

logging.basicConfig(
    filename=logfile,
    filemode="a+",
    format=formatter,
    datefmt=date_format,
    level=logging.ERROR
)

