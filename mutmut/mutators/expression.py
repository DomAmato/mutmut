from .base import BaseMutator
from parso.python.tree import (
    Name,
)

class ExpressionMutator(BaseMutator):
    def mutate(self):
        if self.children[0].type == 'operator' and self.children[0].value == ':':
            if len(self.children) > 2 and self.children[2].value == '=':
                self.children = self.children[:]  # we need to copy the list here, to not get in place mutation on the next line!
                self.children[1:] = self.handle_assignment(self.children[1:])
                yield dict(children=self.children)
        elif self.children[1].type == 'operator' and self.children[1].value == '=':
            yield dict(children=self.handle_assignment(self.children))

    def handle_assignment(self, children):
        mutation_index = -1  # we mutate the last value to handle multiple assignment
        if getattr(children[mutation_index], 'value', '---') != 'None':
            x = ' None'
        else:
            x = ' ""'
        children = children[:]
        children[mutation_index] = Name(value=x, start_pos=children[mutation_index].start_pos)

        return children