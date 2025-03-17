from .base import BaseMutator
from parso.python.tree import (
    Name,
)

class TrailerMutator(BaseMutator):

    def mutate(self):
        if self.children[0].type == 'operator' and self.children[0].value == '[' and self.children[-1].type == 'operator' and self.children[-1].value == ']' and len(self.children) > 2:
            yield from self.subscript_mutation()


    def subscript_mutation(self):
        if len(self.children) == 3 and self.children[1].type == 'keyword' and self.children[1].value == 'None':
            return
        if self.context.is_inside_annassign():
            return
        yield dict(children=[
            self.children[0],
            Name(value='None', start_pos=self.children[1].start_pos),
            self.children[-1],
        ])