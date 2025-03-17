from configparser import (
    ConfigParser,
    NoOptionError,
    NoSectionError,
)
from functools import lru_cache
from pathlib import Path
import fnmatch
import sys
from dataclasses import dataclass
from os.path import (
    isdir,
    isfile,
)
from os import getcwd, sep

@dataclass
class Config:
    also_copy: list[Path]
    do_not_mutate: list[str]
    max_stack_depth: int
    debug: bool
    paths_to_mutate: list[Path]

    def should_ignore_for_mutation(self, path):
        if not str(path).endswith('.py'):
            return True
        for p in self.do_not_mutate:
            if fnmatch.fnmatch(path, p):
                return True
        return False


def guess_paths_to_mutate():
    """Guess the path to source code to mutate

    :rtype: str
    """
    this_dir = getcwd().split(sep)[-1]
    if isdir('lib'):
        return ['lib']
    elif isdir('src'):
        return ['src']
    elif isdir(this_dir):
        return [this_dir]
    elif isdir(this_dir.replace('-', '_')):
        return [this_dir.replace('-', '_')]
    elif isdir(this_dir.replace(' ', '_')):
        return [this_dir.replace(' ', '_')]
    elif isdir(this_dir.replace('-', '')):
        return [this_dir.replace('-', '')]
    elif isdir(this_dir.replace(' ', '')):
        return [this_dir.replace(' ', '')]
    if isfile(this_dir + '.py'):
        return [this_dir + '.py']
    raise FileNotFoundError(
        'Could not figure out where the code to mutate is. '
        'Please specify it by adding "paths_to_mutate=code_dir" in setup.cfg to the [mutmut] section.')


def config_reader():
    path = Path('pyproject.toml')
    if path.exists():
        if sys.version_info >= (3, 11):
            from tomllib import loads
        else:
            # noinspection PyPackageRequirements
            from toml import loads
        data = loads(path.read_text('utf-8'))

        try:
            config = data['tool']['mutmut']
        except KeyError:
            pass
        else:
            def s(key, default):
                try:
                    result = config[key]
                except KeyError:
                    return default
                return result
            return s

    config_parser = ConfigParser()
    config_parser.read('setup.cfg')

    def s(key, default):
        try:
            result = config_parser.get('mutmut', key)
        except (NoOptionError, NoSectionError):
            return default
        if isinstance(default, list):
            if '\n' in result:
                result = [x for x in result.split("\n") if x]
            else:
                result = [result]
        elif isinstance(default, bool):
            result = result.lower() in ('1', 't', 'true')
        elif isinstance(default, int):
            result = int(result)
        return result
    return s


@lru_cache()
def read_config():
    s = config_reader()

    return Config(
        do_not_mutate=s('do_not_mutate', []),
        also_copy=[
            Path(y)
            for y in s('also_copy', [])
        ] + [
            Path('tests/'),
            Path('test/'),
            Path('setup.cfg'),
            Path('pyproject.toml'),
        ] + list(Path('.').glob('test*.py')),
        max_stack_depth=s('max_stack_depth', -1),
        debug=s('debug', False),
        paths_to_mutate=[
            Path(y)
            for y in s('paths_to_mutate', [])
        ] or guess_paths_to_mutate()
    )