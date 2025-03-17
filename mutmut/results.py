from collections import defaultdict
from mutmut.stats import StatManager

class ListAllTestsResult:
    def __init__(self, ids, stats: StatManager):
        self.ids = ids
        self.stats = stats

    def clear_out_obsolete_test_names(self):
        count_before = sum(len(x) for x in self.stats.tests_by_mangled_function_name)
        self.stats.tests_by_mangled_function_name = defaultdict(set, **{
            k: {test_name for test_name in test_names if test_name in self.ids}
            for k, test_names in self.stats.tests_by_mangled_function_name.items()
        })
        count_after = sum(len(x) for x in self.stats.tests_by_mangled_function_name)
        if count_before != count_after:
            print(f'Removed {count_before - count_after} obsolete test names')
            self.stats.save_stats()

    def new_tests(self, collected_test_names):
        return self.ids - collected_test_names