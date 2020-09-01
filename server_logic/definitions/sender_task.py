from collections import namedtuple

SenderTask = namedtuple("SenderTask", ["service", "context"])
ExecutionTask = namedtuple("ExecutionTask", ["func", "args", "kwargs"])
