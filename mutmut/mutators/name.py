from .base import BaseMutator

class NameMutator(BaseMutator):
    def mutate(self):
        simple_mutants = {
            'True': 'False',
            'False': 'True',
            'deepcopy': 'copy',
            'None': '""',
            # TODO: probably need to add a lot of things here... some builtins maybe, what more?
        }
        if self.value in simple_mutants:
            yield dict(value=simple_mutants[self.value])

        if self.node.parent.type == 'trailer' and self.node.parent.children[0].type == 'operator' and self.node.parent.children[0].value in ('(', ']'):
            yield dict(value='None')

        # Mutate `b` in `a=b`, but not `a`!
        if self.node.parent.type == 'argument' and self.node.parent.children[0] != self.node and self.node.parent.children[0].type != 'operator':
            yield dict(value='None')

        # Mutate `b` in `a=b`, but not `a`!
        if self.node.parent.type == 'arglist':
            yield dict(value='None')