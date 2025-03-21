

import ast
from contextlib import contextmanager
from datetime import datetime
from hashlib import md5
from io import TextIOWrapper
import json
import os
from pathlib import Path
import shutil
from signal import SIGTERM
from textwrap import dedent, indent
from typing import Any

from parso import (
    parse,
    ParserSyntaxError
    )
from mutmut.utils import NEVER_MUTATE_FUNCTION_NAMES, NEVER_MUTATE_FUNCTION_CALLS, CLASS_NAME_SEPARATOR, strip_prefix, walk_source_files, walk_all_files
from mutmut.config import Config
from mutmut.mutators import (
    OperationMutator,
    KeywordMutator,
    NumberMutator,
    NameMutator,
    StringMutator,
    ArgumentMutator,
    ArgListMutator,
    LogicMutator,
    LambdaMutator,
    ExpressionMutator,
    DecoratorMutator,
    TrailerMutator
)


MUTATION_BY_AST_TYPE = {
    'operator': OperationMutator,
    'keyword': KeywordMutator,
    'number': NumberMutator,
    'name': NameMutator,
    'string': StringMutator,
    'argument': ArgumentMutator,
    'arglist': ArgListMutator,
    'or_test': LogicMutator,
    'and_test': LogicMutator,
    'lambdef': LambdaMutator,
    'expr_stmt': ExpressionMutator,
    'decorator': DecoratorMutator,
    'annassign': ExpressionMutator,
    'trailer': TrailerMutator,
}

# noinspection PyUnresolvedReferences
# language=python
trampoline_impl = """
from inspect import signature as _mutmut_signature
from typing import Annotated
from typing import Callable
from typing import ClassVar


MutantDict = Annotated[dict[str, Callable], "Mutant"]


def _mutmut_trampoline(orig, mutants, *args, **kwargs):
    import os
    mutant_under_test = os.environ['MUTANT_UNDER_TEST']
    if mutant_under_test == 'fail':
        from mutmut.exceptions import MutmutProgrammaticFailException
        raise MutmutProgrammaticFailException('Failed programmatically')      
    elif mutant_under_test == 'stats':
        from mutmut.stats import MUTATION_STATS
        MUTATION_STATS.record_trampoline_hit(orig.__module__ + '.' + orig.__name__)
        result = orig(*args, **kwargs)
        return result  # for the yield case
    prefix = orig.__module__ + '.' + orig.__name__ + '__mutmut_'
    if not mutant_under_test.startswith(prefix):
        result = orig(*args, **kwargs)
        return result  # for the yield case
    mutant_name = mutant_under_test.rpartition('.')[-1]
    result = mutants[mutant_name](*args, **kwargs)
    return result

"""
yield_from_trampoline_impl = trampoline_impl.replace('result = ', 'result = yield from ').replace('_mutmut_trampoline', '_mutmut_yield_from_trampoline')

class FuncContext:
    def __init__(self, no_mutate_lines=None, dict_synonyms=None):
        self.count = 1
        self.mutants = []
        self.stack = []
        self.dict_synonyms = {'dict'} | (dict_synonyms or set())
        self.no_mutate_lines = no_mutate_lines or []

    def exclude_node(self, node):
        if node.start_pos[0] in self.no_mutate_lines:
            return True
        return False

    def is_inside_annassign(self):
        for node in self.stack:
            if node.type == 'annassign':
                return True
        return False

    def is_inside_dict_synonym_call(self):
        for node in self.stack:
            if node.type == 'atom_expr' and node.children[0].type == 'name' and node.children[0].value in self.dict_synonyms:
                return True
        return False

class SourceFileMutationData:
    def __init__(self, path: Path, mutation_path: Path):
        self.estimated_time_of_tests_by_mutant = {}
        self.path = path
        self.meta_path = mutation_path / (str(path) + '.meta')
        self.meta = None
        self.key_by_pid = {}
        self.exit_code_by_key = {}
        self.hash_by_function_name = {}
        self.start_time_by_pid = {}
        self.estimated_time_of_tests_by_pid = {}

    def load(self):
        try:
            with open(self.meta_path) as f:
                self.meta = json.load(f)
        except FileNotFoundError:
            return

        self.exit_code_by_key = self.meta.pop('exit_code_by_key')
        self.hash_by_function_name = self.meta.pop('hash_by_function_name')
        assert not self.meta, self.meta  # We should read all the data!

    def register_pid(self, *, pid, key, estimated_time_of_tests):
        self.key_by_pid[pid] = key
        self.start_time_by_pid[pid] = datetime.now()
        self.estimated_time_of_tests_by_pid[pid] = estimated_time_of_tests

    def register_result(self, *, pid, exit_code):
        assert self.key_by_pid[pid] in self.exit_code_by_key
        self.exit_code_by_key[self.key_by_pid[pid]] = exit_code
        # TODO: maybe rate limit this? Saving on each result can slow down mutation testing a lot if the test run is fast.
        del self.key_by_pid[pid]
        del self.start_time_by_pid[pid]
        self.save()

    def stop_children(self):
        for pid in self.key_by_pid.keys():
            os.kill(pid, SIGTERM)

    def save(self):
        with open(self.meta_path, 'w') as f:
            json.dump(dict(
                exit_code_by_key=self.exit_code_by_key,
                hash_by_function_name=self.hash_by_function_name,
            ), f, indent=4)

class MutantGenerator:
    def __init__(self, config: Config):
        self.mutants = []
        self.source_file_mutation_data = None
        self.sentinel = object()
        self.config = config

    def copy_src_dir(self):
        for root, filename in walk_all_files(self.config.paths_to_mutate):
            path = Path(root) / filename
            output_path = self.config.mutation_path / path
            os.makedirs(output_path.parent, exist_ok=True)
            shutil.copy(path, output_path)

    def copy_tests_dir(self):
        for root, filename in walk_all_files(self.config.test_dirs):
            path = Path(root) / filename
            output_path = self.config.mutation_path / path
            os.makedirs(output_path.parent, exist_ok=True)
            shutil.copy(path, output_path)

    def create_mutants(self):
        for path in walk_source_files(self.config.paths_to_mutate):
            print(path)
            output_path = self.config.mutation_path / path
            os.makedirs(output_path.parent, exist_ok=True)

            if self.config.should_ignore_for_mutation(path):
                shutil.copy(path, output_path)
            else:
                self.create_mutants_for_file(path, output_path)


    def copy_also_copy_files(self):
        assert isinstance(self.config.also_copy, list)
        for path in self.config.also_copy:
            print('     also copying', path)
            path = Path(path)
            destination = self.config.mutation_path / path
            if not path.exists():
                continue
            if path.is_file():
                shutil.copy(path, destination)
            else:
                shutil.copytree(path, destination, dirs_exist_ok=True)


    def pragma_no_mutate_lines(self, source: str):
        return {
            i + 1
            for i, line in enumerate(source.split('\n'))
            if '# pragma:' in line and 'no mutate' in line.partition('# pragma:')[-1]
        }


    def create_mutants_for_file(self, filename: Path, output_path: Path):
        input_stat = os.stat(filename)

        if output_path.exists() and output_path.stat().st_mtime == input_stat.st_mtime:
            # print('    skipped', output_path, 'already up to date')
            return

        with open(filename) as f:
            source = f.read()

        with open(output_path, 'w') as out:
            mutant_names, hash_by_function_name = self.write_all_mutants_to_file(out=out, source=source, filename=filename)

        # validate no syntax errors of mutants
        with open(output_path) as f:
            try:
                ast.parse(f.read())
            except (IndentationError, SyntaxError) as e:
                print(output_path, 'has invalid syntax: ', e)
                exit(1)

        source_file_mutation_data = SourceFileMutationData(path=filename, mutation_path=self.config.mutation_path)
        module_name = strip_prefix(str(filename)[:-len(filename.suffix)].replace(os.sep, '.'), prefix='src.')

        source_file_mutation_data.exit_code_by_key = {
            '.'.join([module_name, x]).replace('.__init__.', '.'): None
            for x in mutant_names
        }
        source_file_mutation_data.hash_by_function_name = hash_by_function_name
        assert None not in hash_by_function_name
        source_file_mutation_data.save()

        os.utime(output_path, (input_stat.st_atime, input_stat.st_mtime))


    def ensure_ends_with_newline(self, source: str):
        if not source.endswith('\n'):
            return source + '\n'
        else:
            return source


    def write_all_mutants_to_file(self, *, out: TextIOWrapper, source: str, filename: Path):
        no_mutate_lines = self, self.pragma_no_mutate_lines(source)

        hash_by_function_name = {}
        mutant_names = []

        try:
            ast = parse(self.ensure_ends_with_newline(source), error_recovery=False)
        except ParserSyntaxError:
            print(f'Warning: unsupported syntax in {filename}, skipping')
            out.write(source)
            return [], {}

        for type_, x, name_and_hash, mutant_name in self.yield_mutants_for_module(ast, no_mutate_lines):
            out.write(x)
            if mutant_name:
                mutant_names.append(mutant_name)
            if name_and_hash:
                assert type_ == 'orig'
                name, hash = name_and_hash
                hash_by_function_name[name] = hash

        return mutant_names, hash_by_function_name


    def build_trampoline(self, *, orig_name: str, mutants: list[str], class_name: str | None, is_generator:bool):
        assert orig_name not in NEVER_MUTATE_FUNCTION_NAMES

        mangled_name = self.mangle_function_name(name=orig_name, class_name=class_name)

        mutants_dict = f'{mangled_name}__mutmut_mutants : ClassVar[MutantDict] = {{\n' + ', \n    '.join(f'{repr(m)}: {m}' for m in mutants) + '\n}'
        access_prefix = ''
        access_suffix = ''
        if class_name is not None:
            access_prefix = f'object.__getattribute__(self, "'
            access_suffix = '")'

        if is_generator:
            yield_statement = 'yield from '  # note the space at the end!
            trampoline_name = '_mutmut_yield_from_trampoline'
        else:
            yield_statement = ''
            trampoline_name = '_mutmut_trampoline'

        return f"""
{mutants_dict}

def {orig_name}({'self, ' if class_name is not None else ''}*args, **kwargs):
    result = {yield_statement}{trampoline_name}({access_prefix}{mangled_name}__mutmut_orig{access_suffix}, {access_prefix}{mangled_name}__mutmut_mutants{access_suffix}, *args, **kwargs)
    return result 

{orig_name}.__signature__ = _mutmut_signature({mangled_name}__mutmut_orig)
{mangled_name}__mutmut_orig.__name__ = '{mangled_name}'
"""


    @contextmanager
    def rename_function_node(self, node, *, suffix, class_name):
        orig_name = node.name.value

        mangled_name = self.mangle_function_name(name=orig_name, class_name=class_name)

        node.name.value = mangled_name + f'__mutmut_{suffix}'
        yield
        node.name.value = orig_name


    def filter_funcdef_children(self, children: list[Any]):
        # Throw away type annotation for return type
        r = []
        in_annotation = False
        for c in children:
            if c.type == 'operator':
                if c.value == '->':
                    in_annotation = True
                if c.value == ':':
                    in_annotation = False

            if not in_annotation:
                r.append(c)
        return r


    def yield_mutants_for_node(self, *, func_node, class_name=None, context, node):
        # do not mutate static typing annotations
        if node.type == 'tfpdef':
            return

        # Some functions should not be mutated
        if node.type == 'atom_expr' and node.children[0].type == 'name' and node.children[0].value in NEVER_MUTATE_FUNCTION_CALLS:
            return

        # The rest
        if hasattr(node, 'children'):
            children = node.children
            if node.type == 'funcdef':
                children = self.filter_funcdef_children(children)
            for child_node in children:
                context.stack.append(child_node)
                try:
                    yield from self.yield_mutants_for_node(func_node=func_node, class_name=class_name, context=context, node=child_node)
                finally:
                    context.stack.pop()

        mutation = MUTATION_BY_AST_TYPE.get(node.type)
        if not mutation:
            return

        if context.exclude_node(node):
            return

        old_value = getattr(node, 'value', self.sentinel)
        old_children = getattr(node, 'children', self.sentinel)

        for m in mutation(
            context=context,
            node=node,
            value=getattr(node, 'value', None),
            children=getattr(node, 'children', None),
        ).mutate():
            new_value = m.get('value', self.sentinel)
            new_children = m.get('children', self.sentinel)
            assert new_value is not self.sentinel or new_children is not self.sentinel
            if new_value is not self.sentinel:
                assert old_value != new_value
                setattr(node, 'value', new_value)
            if new_children is not self.sentinel:
                assert isinstance(new_children, list)
                assert old_children != new_children
                setattr(node, 'children', new_children)

            # noinspection PyArgumentList
            with self.rename_function_node(func_node, suffix=f'{context.count}', class_name=class_name):
                code = func_node.get_code()
                if self.valid_syntax(code):
                    context.count += 1

                    context.mutants.append(func_node.name.value)
                    yield 'mutant', code, None, func_node.name.value

                if old_value is not self.sentinel:
                    setattr(node, 'value', old_value)
                if old_children is not self.sentinel:
                    setattr(node, 'children', old_children)


    def valid_syntax(self, code: str):
        try:
            ast.parse(dedent(code))
            return True
        except (SyntaxError, IndentationError):
            return False

    def is_generator(self, node) -> bool:
        assert node.type == 'funcdef'

        def _is_generator(n):
            if n is not node and n.type in ('funcdef', 'classdef'):
                return False

            if n.type == 'keyword' and n.value == 'yield':
                return True

            for c in getattr(n, 'children', []):
                if _is_generator(c):
                    return True
            return False
        return _is_generator(node)


    def yield_mutants_for_function(self, node, *, class_name=None, no_mutate_lines):
        assert node.type == 'funcdef'

        if node.name.value in NEVER_MUTATE_FUNCTION_NAMES:
            yield 'filler', node.get_code(), None, None
            return

        hash_of_orig = md5(node.get_code().encode()).hexdigest()

        orig_name = node.name.value
        # noinspection PyArgumentList
        with self.rename_function_node(node, suffix='orig', class_name=class_name):
            yield 'orig', node.get_code(), (orig_name, hash_of_orig), None

        context = FuncContext(no_mutate_lines=no_mutate_lines)

        return_annotation_started = False

        for child_node in node.children:
            if child_node.type == 'operator' and child_node.value == '->':
                return_annotation_started = True

            if return_annotation_started and child_node.type == 'operator' and child_node.value == ':':
                return_annotation_started = False

            if return_annotation_started:
                continue

            context.stack.append(child_node)
            try:
                yield from self.yield_mutants_for_node(func_node=node, class_name=class_name, node=child_node, context=context)
            finally:
                context.stack.pop()

        trampoline = self.build_trampoline(orig_name=node.name.value, mutants=context.mutants, class_name=class_name, is_generator=self.is_generator(node))
        if class_name is not None:
            trampoline = indent(trampoline, '    ')
        yield 'trampoline', trampoline, None, None
        yield 'filler', '\n\n', None, None


    def yield_mutants_for_class(self, node, no_mutate_lines):
        assert node.type == 'classdef'
        for child_node in node.children:
            if child_node.type == 'suite':
                yield from self.yield_mutants_for_class_body(child_node, no_mutate_lines=no_mutate_lines)
            else:
                yield 'filler', child_node.get_code(), None, None


    def yield_mutants_for_class_body(self, node, no_mutate_lines):
        assert node.type == 'suite'
        class_name = node.parent.name.value

        for child_node in node.children:
            if child_node.type == 'funcdef':
                yield from self.yield_mutants_for_function(child_node, class_name=class_name, no_mutate_lines=no_mutate_lines)
            else:
                yield 'filler', child_node.get_code(), None, None


    def is_from_future_import_node(self, c):
        if c.type == 'simple_stmt':
            if c.children:
                c2 = c.children[0]
                if c2.type == 'import_from' and c2.children[1].type == 'name' and c2.children[1].value == '__future__':
                    return True
        return False


    def yield_future_imports(self, node):
        for c in node.children:
            if self.is_from_future_import_node(c):
                yield 'filler', c.get_code(), None, None


    def yield_mutants_for_module(self, node, no_mutate_lines):
        assert node.type == 'file_input'

        # First yield `from __future__`, then the rest
        yield from self.yield_future_imports(node)

        yield 'trampoline_impl', trampoline_impl, None, None
        yield 'trampoline_impl', yield_from_trampoline_impl, None, None
        yield 'filler', '\n', None, None
        for child_node in node.children:
            if child_node.type == 'funcdef':
                yield from self.yield_mutants_for_function(child_node, no_mutate_lines=no_mutate_lines)
            elif child_node.type == 'classdef':
                yield from self.yield_mutants_for_class(child_node, no_mutate_lines=no_mutate_lines)
            elif self.is_from_future_import_node(child_node):
                # Don't yield `from __future__` after trampoline
                pass
            else:
                yield 'filler', child_node.get_code(), None, None

    def mangle_function_name(self, *, name, class_name):
        assert CLASS_NAME_SEPARATOR not in name
        if class_name:
            assert CLASS_NAME_SEPARATOR not in class_name
            prefix = f'x{CLASS_NAME_SEPARATOR}{class_name}{CLASS_NAME_SEPARATOR}'
        else:
            prefix = 'x_'
        return f'{prefix}{name}'