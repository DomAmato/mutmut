from .base import BaseMutator

class StringMutator(BaseMutator):
    def mutate(self):
        if self.context.is_inside_annassign():
            return

        prefix = self.value[:min([x for x in [self.value.find('"'), self.value.find("'")] if x != -1])]
        self.value = self.value[len(prefix):]

        if self.value.startswith('"""') or self.value.startswith("'''"):
            # We assume here that triple-quoted stuff are docs or other things
            # that mutation is meaningless for
            return prefix + self.value
        yield dict(value=prefix + self.value[0] + 'XX' + self.value[1:-1] + 'XX' + self.value[-1])