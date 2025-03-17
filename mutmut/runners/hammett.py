from .base import TestRunner
from ..stats import MUTATION_STATS
from ..config import Config

class HammettRunner(TestRunner):
    def __init__(self, config: Config):
        super().__init__(config)
        self.hammett_kwargs = None

    def run_stats(self, *, tests):
        import hammett
        print('Running hammett stats...')

        def post_test_callback(_name, **_):
            for function in MUTATION_STATS:
                MUTATION_STATS.tests_by_mangled_function_name[function].add(_name)
            MUTATION_STATS.clear()

        return hammett.main(quiet=True, fail_fast=True, disable_assert_analyze=True, post_test_callback=post_test_callback, use_cache=False, insert_cwd=False)

    def run_forced_fail(self):
        import hammett
        return hammett.main(quiet=True, fail_fast=True, disable_assert_analyze=True, use_cache=False, insert_cwd=False)

    def prepare_main_test_run(self):
        import hammett
        self.hammett_kwargs = hammett.main_setup(
            quiet=True,
            fail_fast=True,
            disable_assert_analyze=True,
            use_cache=False,
            insert_cwd=False,
        )

    def run_tests(self, *, mutant_name, tests):
        import hammett
        hammett.Config.workerinput = dict(workerinput=f'_{mutant_name}')
        return hammett.main_run_tests(**self.hammett_kwargs, tests=tests)

