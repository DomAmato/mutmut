from dataclasses import dataclass
from enum import Enum
import json
from mutmut.generator import SourceFileMutationData

class Status(Enum):
    NOT_CHECKED = 'not checked'
    KILLED = 'killed'
    SURVIVED = 'survived'
    NO_TESTS = 'no tests'
    INTERRUPTED = 'check was interrupted by user'
    SKIPPED = 'skipped'
    SUSPICIOUS = 'suspicious'
    TIMEOUT = 'timeout'

STATUS_BY_EXIT_CODE = {
    1: Status.KILLED,
    3: Status.KILLED,  # internal error in pytest means a kill
    -24: Status.KILLED,
    0: Status.SURVIVED,
    5: Status.NO_TESTS,
    2: Status.INTERRUPTED,
    None: Status.NOT_CHECKED,
    33: Status.NO_TESTS,
    34: Status.SKIPPED,
    35: Status.SUSPICIOUS,
    36: Status.TIMEOUT,
    24: Status.TIMEOUT,  # SIGXCPU
    152: Status.TIMEOUT,  # SIGXCPU
    255: Status.TIMEOUT,
}

EMOJI_BY_STATUS = {
    Status.SURVIVED: '🙁',
    Status.NO_TESTS: '🫥',
    Status.TIMEOUT: '⏰',
    Status.SUSPICIOUS: '🤔',
    Status.SKIPPED: '🔇',
    Status.INTERRUPTED: '🛑',
    Status.NOT_CHECKED: '?',
    Status.KILLED: '🎉',
}

EXIT_CODE_TO_EMOJI = {
    exit_code: EMOJI_BY_STATUS[status]
    for exit_code, status in STATUS_BY_EXIT_CODE.items()
}

@dataclass
class Stat:
    not_checked: int
    killed: int
    survived: int
    total: int
    no_tests: int
    skipped: int
    suspicious: int
    timeout: int
    check_was_interrupted_by_user: int
    
@dataclass
class StatCollection:
    tests_by_mangled_function_name: dict[str]
    duration_by_test: dict[str]
    stats_time: float

class StatManager:

    def __init__(self):
        self.stats = StatCollection({}, {}, 0.0)
        self.stats_set = set()
        self.load_stats()

    def collect_stat(self, m: SourceFileMutationData):
        r = {
            k.replace(' ', '_'): 0
            for k in STATUS_BY_EXIT_CODE.values()
        }
        for k, v in m.exit_code_by_key.items():
            # noinspection PyTypeChecker
            r[STATUS_BY_EXIT_CODE[v].replace(' ', '_')] += 1
        return Stat(
            **r,
            total=sum(r.values()),
        )


    def calculate_summary_stats(self, source_file_mutation_data_by_path):
        stats = [self.collect_stat(x) for x in source_file_mutation_data_by_path.values()]
        return Stat(
            not_checked=sum(x.not_checked for x in stats),
            killed=sum(x.killed for x in stats),
            survived=sum(x.survived for x in stats),
            total=sum(x.total for x in stats),
            no_tests=sum(x.no_tests for x in stats),
            skipped=sum(x.skipped for x in stats),
            suspicious=sum(x.suspicious for x in stats),
            timeout=sum(x.timeout for x in stats),
            check_was_interrupted_by_user=sum(x.check_was_interrupted_by_user for x in stats),
        )


    def print_stats(self, source_file_mutation_data_by_path, print_status, force_output=False):
        s = self.calculate_summary_stats(source_file_mutation_data_by_path)
        print_status(f'{(s.total - s.not_checked)}/{s.total}  🎉 {s.killed} 🫥 {s.no_tests}  ⏰ {s.timeout}  🤔 {s.suspicious}  🙁 {s.survived}  🔇 {s.skipped}', force_output=force_output)



    def load_stats(self, stat_file: str = 'mutants/mutmut-stats.json'):
        did_load = False
        try:
            with open(stat_file) as f:
                data = json.load(f)
                for k, v in data.pop('tests_by_mangled_function_name').items():
                    self.stats.tests_by_mangled_function_name[k] |= set(v)
                self.stats.duration_by_test = data.pop('duration_by_test')
                self.stats.stats_time = data.pop('stats_time')
                assert not data, data
                did_load = True
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return did_load


    def save_stats(self, stat_file: str = 'mutants/mutmut-stats.json'):
        with open(stat_file, 'w') as f:
            json.dump(dict(
                tests_by_mangled_function_name={k: list(v) for k, v in self.stats.tests_by_mangled_function_name.items()},
                duration_by_test=self.stats.duration_by_test,
                stats_time=self.stats.stats_time,
            ), f, indent=4)

    @property
    def tests_by_mangled_function_name(self):
        return self.stats.tests_by_mangled_function_name
    
    @property
    def duration_by_test(self):
        return self.stats.duration_by_test
    
    @property
    def stats_time(self):
        return self.stats.stats_time