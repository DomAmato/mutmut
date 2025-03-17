from .base import TestRunner
from ..exceptions import BadTestExecutionCommandsException, CollectTestsFailedException
from ..utils import strip_prefix
from ..stats import MUTATION_STATS
from ..results import ListAllTestsResult

class PytestRunner(TestRunner):
    # noinspection PyMethodMayBeStatic
    def execute_pytest(self, params, **kwargs):
        import pytest
        params += ['--rootdir=.']
        if self.config.debug:
            params = ['-vv'] + params
            print('python -m pytest ', ' '.join(params))
        exit_code = int(pytest.main(params, **kwargs))
        if self.config.debug:
            print('    exit code', exit_code)
        if exit_code == 4:
            raise BadTestExecutionCommandsException(params)
        return exit_code

    def run_stats(self, *, tests):
        class StatsCollector:
            # noinspection PyMethodMayBeStatic
            def pytest_runtest_teardown(self, item, nextitem):
                for function in MUTATION_STATS.functions:
                    MUTATION_STATS.tests_by_mangled_function_name[function].add(strip_prefix(item._nodeid, prefix='mutants/'))
                MUTATION_STATS.functions.clear()

            # noinspection PyMethodMayBeStatic
            def pytest_runtest_makereport(self, item, call):
                MUTATION_STATS.duration_by_test[item.nodeid] = call.duration

        stats_collector = StatsCollector()

        with self.change_cwd('mutants'):
            return int(self.execute_pytest(['-x', '-q', '--import-mode=append'] + list(tests), plugins=[stats_collector]))

            """
            new option --import-mode to allow to change test module importing behaviour to append to sys.path instead of prepending. 
            This better allows to run test modules against installed versions of a package even if the package under test has the same import root. 
            In this example:

                testing/__init__.py
                testing/test_pkg_under_test.py
                pkg_under_test/

            the tests will run against the installed version of pkg_under_test when --import-mode=append is used 
            whereas by default they would always pick up the local version.
            """
    def run_tests(self, *, mutant_name, tests):
        with self.change_cwd('mutants'):
            return int(self.execute_pytest(['-x', '-q', '--import-mode=append'] + list(tests)))

    def run_forced_fail(self):
        with self.change_cwd('mutants'):
            return int(self.execute_pytest(['-x', '-q', '--import-mode=append']))

    def list_all_tests(self):
        class TestsCollector:
            def pytest_collection_modifyitems(self, items):
                self.nodeids = {item.nodeid for item in items}

        collector = TestsCollector()

        with self.change_cwd('mutants'):
            exit_code = int(self.execute_pytest(['-x', '-q', '--collect-only'], plugins=[collector]))
            if exit_code != 0:
                raise CollectTestsFailedException()

        return ListAllTestsResult(ids=collector.nodeids)

