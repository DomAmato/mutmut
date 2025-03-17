from .base import BaseMutator

class ArgListMutator(BaseMutator):
    def mutate(self):
        for i, child_node in enumerate(self.children):
            if child_node.type in ('name', 'argument'):
                offset = 1
                if len(self.children) > i+1:
                    if self.children[i+1].type == 'operator' and self.children[i+1].value == ',':
                        offset = 2
                yield dict(children=self.children[:i] + self.children[i + offset:])