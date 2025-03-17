import fnmatch
import gc
import itertools
import os
import resource
import signal
import sys
from datetime import (
    datetime,
    timedelta,
)
from difflib import unified_diff
from io import TextIOBase
from math import ceil
from os import (
    makedirs,
    walk,
)

from pathlib import Path
from threading import Thread
from time import (
    process_time,
    sleep,
)

import click
from parso import (
    parse,
)
from setproctitle import setproctitle
from mutmut.config import read_config
from mutmut.generator import SourceFileMutationData, MutantGenerator
from mutmut.stats import STATUS_BY_EXIT_CODE, EMOJI_BY_STATUS, MUTATION_STATS
from mutmut.utils import CLASS_NAME_SEPARATOR, walk_source_files
from mutmut.exceptions import MutmutProgrammaticFailException, CollectTestsFailedException
from mutmut.runners.pytest import PytestRunner

mutmut_config = read_config()
mutant_generatior = MutantGenerator(mutmut_config)


spinner = itertools.cycle('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')


def status_printer():
    """Manage the printing and in-place updating of a line of characters

    .. note::
        If the string is longer than a line, then in-place updating may not
        work (it will print a new line at each refresh).
    """
    last_len = [0]
    last_update = [datetime(1900, 1, 1)]
    update_threshold = timedelta(seconds=0.1)

    def p(s, *, force_output=False):
        if not force_output and (datetime.now() - last_update[0]) < update_threshold:
            return
        s = next(spinner) + ' ' + s
        len_s = len(s)
        output = '\r' + s + (' ' * max(last_len[0] - len_s, 0))
        sys.__stdout__.write(output)
        sys.__stdout__.flush()
        last_len[0] = len_s
    return p


print_status = status_printer()


def run_forced_fail(runner):
    os.environ['MUTANT_UNDER_TEST'] = 'fail'
    with CatchOutput(spinner_title='Running forced fail test') as catcher:
        try:
            if runner.run_forced_fail() == 0:
                catcher.dump_output()
                print("FAILED")
                os._exit(1)
        except MutmutProgrammaticFailException:
            pass
    os.environ['MUTANT_UNDER_TEST'] = ''
    print('    done')


def tests_for_mutant_names(mutant_names):
    tests = set()
    for mutant_name in mutant_names:
        if '*' in mutant_name:
            for name, tests_of_this_name in MUTATION_STATS.tests_by_mangled_function_name.items():
                if fnmatch.fnmatch(name, mutant_name):
                    tests |= set(tests_of_this_name)
        else:
            tests |= set(MUTATION_STATS.tests_by_mangled_function_name[mangled_name_from_mutant_name(mutant_name)])
    return tests


def read_mutants_ast(path):
    with open(Path('mutants') / path) as f:
        return parse(f.read(), error_recovery=False)


def read_orig_ast(path):
    with open(path) as f:
        return parse(f.read())


def find_ast_node(ast, function_name, orig_function_name):
    function_name = function_name.rpartition('.')[-1]
    orig_function_name = orig_function_name.rpartition('.')[-1]

    for node in ast.children:
        if node.type == 'classdef':
            (body,) = [x for x in node.children if x.type == 'suite']
            result = find_ast_node(body, function_name=function_name, orig_function_name=orig_function_name)
            if result:
                return result
        if node.type == 'funcdef' and node.name.value == function_name:
            node.name.value = orig_function_name
            return node


def read_original_ast_node(ast, mutant_name):
    orig_function_name, class_name = orig_function_and_class_names_from_key(mutant_name)
    orig_name = mangled_name_from_mutant_name(mutant_name) + '__mutmut_orig'

    result = find_ast_node(ast, function_name=orig_name, orig_function_name=orig_function_name)
    if not result:
        raise FileNotFoundError(f'Could not find original function "{orig_function_name}"')
    return result


def read_mutant_ast_node(ast, mutant_name):
    orig_function_name, class_name = orig_function_and_class_names_from_key(mutant_name)
    result = find_ast_node(ast, function_name=mutant_name, orig_function_name=orig_function_name)
    if not result:
        raise FileNotFoundError(f'Could not find mutant "{mutant_name}"')
    return result


def find_mutant(mutant_name):
    for path in walk_source_files(mutmut_config):
        if mutmut_config.should_ignore_for_mutation(path):
            continue

        m = SourceFileMutationData(path=path)
        m.load()
        if mutant_name in m.exit_code_by_key:
            return m

    raise FileNotFoundError(f'Could not find mutant {mutant_name}')

def get_diff_for_mutant(mutant_name, source=None, path=None):
    if path is None:
        m = find_mutant(mutant_name)
        path = m.path
        status = STATUS_BY_EXIT_CODE[m.exit_code_by_key[mutant_name]]
    else:
        status = 'not checked'

    print(f'# {mutant_name}: {status}')

    if source is None:
        ast = read_mutants_ast(path)
    else:
        ast = parse(source, error_recovery=False)
    orig_code = read_original_ast_node(ast, mutant_name).get_code().strip()
    mutant_code = read_mutant_ast_node(ast, mutant_name).get_code().strip()

    path = str(path)  # difflib requires str, not Path
    return '\n'.join([
        line
        for line in unified_diff(orig_code.split('\n'), mutant_code.split('\n'), fromfile=path, tofile=path, lineterm='')
    ])


def stop_all_children(mutants):
    for m, _, _ in mutants:
        m.stop_children()


def timeout_checker(mutants):
    def inner_timout_checker():
        while True:
            sleep(1)

            now = datetime.now()
            for m, mutant_name, result in mutants:
                for pid, start_time in m.start_time_by_pid.items():
                    run_time = now - start_time
                    if run_time.total_seconds() > (m.estimated_time_of_tests_by_mutant[mutant_name] + 1) * 4:
                        try:
                            os.kill(pid, signal.SIGXCPU)
                        except ProcessLookupError:
                            pass
    return inner_timout_checker


def run_stats_collection(runner, tests=None):
    if tests is None:
        tests = []  # Meaning all...

    os.environ['MUTANT_UNDER_TEST'] = 'stats'
    os.environ['PY_IGNORE_IMPORTMISMATCH'] = '1'
    start_cpu_time = process_time()

    with CatchOutput(spinner_title='Running stats') as output_catcher:
        collect_stats_exit_code = runner.run_stats(tests=tests)
        if collect_stats_exit_code != 0:
            output_catcher.dump_output()
            print(f'failed to collect stats. runner returned {collect_stats_exit_code}')
            exit(1)

    print('    done')
    if not tests:  # again, meaning all
        MUTATION_STATS.stats_time = process_time() - start_cpu_time

    if not collected_test_names():
        print('failed to collect stats, no active tests found')
        exit(1)

    MUTATION_STATS.save_stats()


def collect_or_load_stats(runner):
    did_load = MUTATION_STATS.load_stats()

    if not did_load:
        # Run full stats
        run_stats_collection(runner)
    else:
        # Run incremental stats
        with CatchOutput(spinner_title='Listing all tests') as output_catcher:
            os.environ['MUTANT_UNDER_TEST'] = 'list_all_tests'
            try:
                all_tests_result = runner.list_all_tests()
            except CollectTestsFailedException:
                output_catcher.dump_output()
                print('Failed to collect list of tests')
                exit(1)

        all_tests_result.clear_out_obsolete_test_names()

        new_tests = all_tests_result.new_tests(collected_test_names())

        if new_tests:
            print(f'Found {len(new_tests)} new tests, rerunning stats collection')
            run_stats_collection(runner, tests=new_tests)




def collect_source_file_mutation_data(*, mutant_names):
    source_file_mutation_data_by_path: dict[str, SourceFileMutationData] = {}

    for path in walk_source_files(mutmut_config.paths_to_mutate):
        if mutmut_config.should_ignore_for_mutation(path):
            continue
        assert path not in source_file_mutation_data_by_path
        m = SourceFileMutationData(path=path)
        m.load()
        source_file_mutation_data_by_path[str(path)] = m

    mutants = [
        (m, mutant_name, result)
        for path, m in source_file_mutation_data_by_path.items()
        for mutant_name, result in m.exit_code_by_key.items()
    ]

    if mutant_names:
        filtered_mutants = [
            (m, key, result)
            for m, key, result in mutants
            if key in mutant_names or any(fnmatch.fnmatch(key, mutant_name) for mutant_name in mutant_names)
        ]
        assert filtered_mutants, f'Filtered for specific mutants, but nothing matches\n\nFilter: {mutant_names}'
        mutants = filtered_mutants
    return mutants, source_file_mutation_data_by_path

def collected_test_names():
    return set(MUTATION_STATS.duration_by_test.keys())


def mangled_name_from_mutant_name(mutant_name):
    assert '__mutmut_' in mutant_name, mutant_name
    return mutant_name.partition('__mutmut_')[0]


def orig_function_and_class_names_from_key(mutant_name):
    r = mangled_name_from_mutant_name(mutant_name)
    _, _, r = r.rpartition('.')
    class_name = None
    if CLASS_NAME_SEPARATOR in r:
        class_name = r[r.index(CLASS_NAME_SEPARATOR) + 1: r.rindex(CLASS_NAME_SEPARATOR)]
        r = r[r.rindex(CLASS_NAME_SEPARATOR) + 1:]
    else:
        assert r.startswith('x_'), r
        r = r[2:]
    return r, class_name
class CatchOutput:
    def __init__(self, callback=lambda s: None, spinner_title=None):
        self.strings = []
        self.spinner_title = spinner_title or ''

        class StdOutRedirect(TextIOBase):
            def __init__(self, catcher):
                self.catcher = catcher

            def write(self, s):
                callback(s)
                if spinner_title:
                    print_status(spinner_title)
                self.catcher.strings.append(s)
                return len(s)
        self.redirect = StdOutRedirect(self)

    # noinspection PyMethodMayBeStatic
    def stop(self):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def start(self):
        if self.spinner_title:
            print_status(self.spinner_title)
        sys.stdout = self.redirect
        sys.stderr = self.redirect
        if mutmut_config.debug:
            self.stop()

    def dump_output(self):
        self.stop()
        for line in self.strings:
            print(line, end='')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        if self.spinner_title:
            print()


@click.group()
def cli():
    pass

def estimated_worst_case_time(mutant_name):
    tests = MUTATION_STATS.tests_by_mangled_function_name.get(mangled_name_from_mutant_name(mutant_name), set())
    return sum(MUTATION_STATS.duration_by_test[t] for t in tests)


@cli.command()
@click.argument('mutant_names', required=False, nargs=-1)
def print_time_estimates(mutant_names):
    assert isinstance(mutant_names, (tuple, list)), mutant_names

    runner = PytestRunner(config=mutmut_config)
    runner.prepare_main_test_run()

    collect_or_load_stats(runner)

    mutants, source_file_mutation_data_by_path = collect_source_file_mutation_data(mutant_names=mutant_names)

    times_and_keys = [
        (estimated_worst_case_time(mutant_name), mutant_name)
        for m, mutant_name, result in mutants
    ]

    for time, key in sorted(times_and_keys):
        if not time:
            print(f'<no tests>', key)
        else:
            print(f'{int(time*1000)}ms', key)


@cli.command()
@click.argument('mutant_name', required=True, nargs=1)
def tests_for_mutant(mutant_name):
    if not MUTATION_STATS.load_stats():
        print('Failed to load stats. Please run mutmut first to collect stats.')
        exit(1)

    tests = tests_for_mutant_names([mutant_name])
    for test in sorted(tests):
        print(test)


@cli.command()
@click.option('--max-children', type=int)
@click.argument('mutant_names', required=False, nargs=-1)
def run(mutant_names, *, max_children):
    assert isinstance(mutant_names, (tuple, list)), mutant_names

    # TODO: run no-ops once in a while to detect if we get false negatives
    # TODO: we should be able to get information on which tests killed mutants, which means we can get a list of tests and how many mutants each test kills. Those that kill zero mutants are redundant!
    os.environ['MUTANT_UNDER_TEST'] = 'mutant_generation'

    start = datetime.now()
    makedirs(Path('mutants'), exist_ok=True)
    with CatchOutput(spinner_title='Generating mutants'):
        mutant_generatior.copy_src_dir()
        mutant_generatior.create_mutants()
        mutant_generatior.copy_also_copy_files()

    time = datetime.now() - start
    print(f'    done in {round(time.total_seconds()*1000)}ms', )

    src_path = (Path('mutants') / 'src')
    source_path = (Path('mutants') / 'source')
    if src_path.exists():
        sys.path.insert(0, str(src_path.absolute()))
    elif source_path.exists():
        sys.path.insert(0, str(source_path.absolute))
    else:
        sys.path.insert(0, os.path.abspath('mutants'))

    # TODO: config/option for runner
    # runner = HammettRunner()
    runner = PytestRunner(config=mutmut_config)
    runner.prepare_main_test_run()

    # TODO: run these steps only if we have mutants to test

    collect_or_load_stats(runner)

    mutants, source_file_mutation_data_by_path = collect_source_file_mutation_data(mutant_names=mutant_names)

    os.environ['MUTANT_UNDER_TEST'] = ''
    with CatchOutput(spinner_title='Running clean tests') as output_catcher:
        tests = tests_for_mutant_names(mutant_names)

        clean_test_exit_code = runner.run_tests(mutant_name=None, tests=tests)
        if clean_test_exit_code != 0:
            output_catcher.dump_output()
            print('Failed to run clean test')
            exit(1)
    print('    done')

    # this can't be the first thing, because it can fail deep inside pytest/django setup and then everything is destroyed
    run_forced_fail(runner)

    runner.prepare_main_test_run()

    def read_one_child_exit_status():
        pid, wait_status = os.wait()
        exit_code = os.waitstatus_to_exitcode(wait_status)
        if mutmut_config.debug:
            print('    worker exit code', exit_code)
        source_file_mutation_data_by_pid[pid].register_result(pid=pid, exit_code=exit_code)

    source_file_mutation_data_by_pid: dict[int, SourceFileMutationData] = {}  # many pids map to one MutationData
    running_children = 0
    if max_children is None:
        max_children = os.cpu_count() or 4

    count_tried = 0

    # Run estimated fast mutants first, calculated as the estimated time for a surviving mutant.
    mutants = sorted(mutants, key=lambda x: estimated_worst_case_time(x[1]))

    gc.freeze()

    start = datetime.now()
    try:
        print('Running mutation testing')

        # Calculate times of tests
        for m, mutant_name, result in mutants:
            mutant_name = mutant_name.replace('__init__.', '')
            tests = MUTATION_STATS.tests_by_mangled_function_name.get(mangled_name_from_mutant_name(mutant_name), [])
            estimated_time_of_tests = sum(MUTATION_STATS.duration_by_test[test_name] for test_name in tests)
            m.estimated_time_of_tests_by_mutant[mutant_name] = estimated_time_of_tests

        Thread(target=timeout_checker(mutants), daemon=True).start()

        # Now do mutation
        for m, mutant_name, result in mutants:
            MUTATION_STATS.print_stats(source_file_mutation_data_by_path, print_status=print_status)

            mutant_name = mutant_name.replace('__init__.', '')

            # Rerun mutant if it's explicitly mentioned, but otherwise let the result stand
            if not mutant_names and result is not None:
                continue

            tests = MUTATION_STATS.tests_by_mangled_function_name.get(mangled_name_from_mutant_name(mutant_name), [])

            # print(tests)
            if not tests:
                m.exit_code_by_key[mutant_name] = 33
                m.save()
                continue

            pid = os.fork()
            if not pid:
                # In the child
                os.environ['MUTANT_UNDER_TEST'] = mutant_name
                setproctitle(f'mutmut: {mutant_name}')

                # Run fast tests first
                tests = sorted(tests, key=lambda test_name: MUTATION_STATS.duration_by_test[test_name])
                if not tests:
                    os._exit(33)

                estimated_time_of_tests = m.estimated_time_of_tests_by_mutant[mutant_name]
                cpu_time_limit = ceil((estimated_time_of_tests + 1) * 2 + process_time()) * 10
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_time_limit, cpu_time_limit))

                with CatchOutput():
                    result = runner.run_tests(mutant_name=mutant_name, tests=tests)

                if result != 0:
                    # TODO: write failure information to stdout?
                    pass
                os._exit(result)
            else:
                # in the parent
                source_file_mutation_data_by_pid[pid] = m
                m.register_pid(pid=pid, key=mutant_name, estimated_time_of_tests=estimated_time_of_tests)
                running_children += 1

            if running_children >= max_children:
                read_one_child_exit_status()
                count_tried += 1
                running_children -= 1

        try:
            while running_children:
                read_one_child_exit_status()
                count_tried += 1
                running_children -= 1
        except ChildProcessError:
            pass
    except KeyboardInterrupt:
        print('Stopping...')
        stop_all_children(mutants)

    t = datetime.now() - start

    MUTATION_STATS.print_stats(source_file_mutation_data_by_path, print_status=print_status, force_output=True)
    print()
    print(f'{count_tried / t.total_seconds():.2f} mutations/second')

    if mutant_names:
        print()
        print('Mutant results')
        print('--------------')
        exit_code_by_key = {}
        # If the user gave a specific list of mutants, print result for these specifically
        for m, mutant_name, result in mutants:
            exit_code_by_key[mutant_name] = m.exit_code_by_key[mutant_name]

        for mutant_name, exit_code in sorted(exit_code_by_key.items()):
            print(EMOJI_BY_STATUS.get(STATUS_BY_EXIT_CODE.get(exit_code), '?'), mutant_name)

        print()


@cli.command()
@click.option('--all', default=False)
def results(all):
    for path in walk_source_files(mutmut_config.paths_to_mutate):
        if not str(path).endswith('.py'):
            continue
        m = SourceFileMutationData(path=path)
        m.load()
        for k, v in m.exit_code_by_key.items():
            status = STATUS_BY_EXIT_CODE[v]
            if status == 'killed' and not all:
                continue
            print(f'    {k}: {status}')


@cli.command()
@click.argument('mutant_name')
def show(mutant_name):
    print(get_diff_for_mutant(mutant_name))
    return


@cli.command()
@click.argument('mutant_name')
def apply(mutant_name):
    # try:
    m = find_mutant(mutant_name)
    path = m.path

    orig_function_name, class_name = orig_function_and_class_names_from_key(mutant_name)
    orig_function_name = orig_function_name.rpartition('.')[-1]

    orig_ast = read_orig_ast(path)
    mutants_ast = read_mutants_ast(path)
    mutant_ast_node = read_mutant_ast_node(mutants_ast, mutant_name=mutant_name)

    mutant_ast_node.name.value = orig_function_name

    for node in orig_ast.children:
        if node.type == 'funcdef' and node.name.value == orig_function_name:
            node.children = mutant_ast_node.children
            break
    else:
        raise FileNotFoundError(f'Could not apply mutant {mutant_name}')

    with open(path, 'w') as f:
        f.write(orig_ast.get_code())
    


if __name__ == '__main__':
    cli()
