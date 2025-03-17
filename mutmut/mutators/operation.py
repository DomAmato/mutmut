from .base import BaseMutator

class OperationMutator(BaseMutator):
    TRANSFORMATIONS = {
            '+': ['-'],
            '-': ['+'],
            '*': ['/'],
            '/': ['*'],
            '//': ['/'],
            '%': ['/'],
            '<<': ['>>'],
            '>>': ['<<'],
            '&': ['|'],
            '|': ['&'],
            '^': ['&'],
            '**': ['*'],
            '~': [''],

            '+=': ['-=', '='],
            '-=': ['+=', '='],
            '*=': ['/=', '='],
            '/=': ['*=', '='],
            '//=': ['/=', '='],
            '%=': ['/=', '='],
            '<<=': ['>>=', '='],
            '>>=': ['<<=', '='],
            '&=': ['|=', '='],
            '|=': ['&=', '='],
            '^=': ['&=', '='],
            '**=': ['*=', '='],
            '~=': ['='],

            '<': ['<='],
            '<=': ['<'],
            '>': ['>='],
            '>=': ['>'],
            '==': ['!='],
            '!=': ['=='],
            '<>': ['=='],
        }
    
    def mutate(self):
        if self.value in ('*', '**') and self.node.parent.type in ('param', 'argument'):
            return

        if self.value == '*' and self.node.parent.type == 'parameters':
            return

        for op in self.TRANSFORMATIONS.get(self.value, []):
            yield dict(value=op)