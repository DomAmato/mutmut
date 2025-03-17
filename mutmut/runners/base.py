
from abc import ABC, abstractmethod
from contextlib import contextmanager
import os
from ..stats import StatManager
from ..config import Config

class TestRunner(ABC):
    def __init__(self, stats: StatManager, config: Config):
        self.config = config
        self.stats = stats

    @abstractmethod
    def run_stats(self, *, tests):
        pass

    @abstractmethod
    def run_forced_fail(self):
        pass

    def prepare_main_test_run(self):
        pass

    @abstractmethod
    def run_tests(self, *, mutant_name, tests):
        pass

    @abstractmethod
    def list_all_tests(self):
        pass

    @contextmanager
    def change_cwd(self, path):
        old_cwd = os.path.abspath(os.getcwd())
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(old_cwd)