from .base import BaseMutator
from parso.python.tree import (
    Name,
)

class ArgumentMutator(BaseMutator):
    def mutate(self):
        if len(self.context.stack) >= 3 and self.context.stack[-3].type in ('power', 'atom_expr'):
            stack_pos_of_power_node = -3
        elif len(self.context.stack) >= 4 and self.context.stack[-4].type in ('power', 'atom_expr'):
            stack_pos_of_power_node = -4
        else:
            return

        power_node = self.context.stack[stack_pos_of_power_node]

        # `dict(a=1)` -> `dict(aXX=1)`
        if power_node.children[0].type == 'name' and power_node.children[0].value in self.context.dict_synonyms:
            c = self.children[0]
            if c.type == 'name':
                self.children = self.children[:]
                self.children[0] = Name(c.value + 'XX', start_pos=c.start_pos, prefix=c.prefix)
                yield dict(children=self.children)