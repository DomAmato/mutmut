from .base import BaseMutator

class KeywordMutator(BaseMutator):
    TRANSFORMATIONS = {
            'not': '',
            'is': 'is not',  # this will cause "is not not" sometimes, so there's a hack to fix that later
            'in': 'not in',
            'break': 'return',
            'continue': 'break',
            'True': 'False',
            'False': 'True',
        }
    
    def mutate(self):
        if len(self.context.stack) > 2 and self.context.stack[-2].type in ('comp_op', 'sync_comp_for') and self.value in ('in', 'is'):
            return

        if len(self.context.stack) > 1 and self.context.stack[-2].type == 'for_stmt':
            return

        mutation = self.TRANSFORMATIONS.get(self.value)

        if mutation is not None:
            yield dict(value=mutation)