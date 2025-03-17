from .base import BaseMutator
from parso.python.tree import (
    Number, Keyword
)

class LambdaMutator(BaseMutator):
    def mutate(self):
        pre, op, post = self.partition_node_list(value=':')

        if len(post) == 1 and getattr(post[0], 'value', None) == 'None':
            yield dict(children=pre + [op] + [Number(value=' 0', start_pos=post[0].start_pos)])
        else:
            yield dict(children=pre + [op] + [Keyword(value=' None', start_pos=post[0].start_pos)])

    def partition_node_list(self, value):
        for i, n in enumerate(self.children):
            if hasattr(n, 'value') and n.value == value:
                return self.children[:i], n, self.children[i + 1:]

        assert False, "didn't find node to split on"