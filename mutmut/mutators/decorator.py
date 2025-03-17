from .base import BaseMutator

class DecoratorMutator(BaseMutator):

    def mutate(self):
        if self.children[-1].type == 'newline':
            yield dict(children=self.children[-1:])