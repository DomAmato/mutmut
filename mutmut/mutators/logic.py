from .base import BaseMutator
from parso.python.tree import (
    Keyword,
)

class LogicMutator(BaseMutator):
    def mutate(self):
        self.children = self.children[:]
        self.children[1] = Keyword(
            value={'and': ' or', 'or': ' and'}[self.children[1].value],
            start_pos=self.node.start_pos,
        )
        yield dict(children=self.children)