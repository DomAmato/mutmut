from collections import defaultdict
from mutmut.stats import MUTATION_STATS

class ListAllTestsResult:
    def __init__(self, ids):
        self.ids = ids

    def clear_out_obsolete_test_names(self):
        count_before = sum(len(x) for x in MUTATION_STATS.tests_by_mangled_function_name)
        MUTATION_STATS.tests_by_mangled_function_name = defaultdict(set, **{
            k: {test_name for test_name in test_names if test_name in self.ids}
            for k, test_names in MUTATION_STATS.tests_by_mangled_function_name.items()
        })
        count_after = sum(len(x) for x in MUTATION_STATS.tests_by_mangled_function_name)
        if count_before != count_after:
            print(f'Removed {count_before - count_after} obsolete test names')
            MUTATION_STATS.save_stats()

    def new_tests(self, collected_test_names):
        return self.ids - collected_test_names