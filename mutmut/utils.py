import os
from os.path import (
    isdir,
    isfile,
)
from pathlib import Path


NEVER_MUTATE_FUNCTION_NAMES = {'__getattribute__', '__setattr__', '__new__'}
NEVER_MUTATE_FUNCTION_CALLS = {'isinstance', 'len'}
CLASS_NAME_SEPARATOR = 'ǁ'

def strip_prefix(s, *, prefix, strict=False):
    if s.startswith(prefix):
        return s[len(prefix):]
    assert strict is False, f"String '{s}' does not start with prefix '{prefix}'"
    return s

def walk_all_files(paths: list[Path]):
    for path in paths:
        if not isdir(path):
            if isfile(path):
                yield '', str(path)
                continue
        for root, dirs, files in os.walk(path):
            for filename in files:
                yield root, filename


def walk_source_files(paths: list[Path]):
    for root, filename in walk_all_files(paths):
        if filename.endswith('.py'):
            yield Path(root) / filename
