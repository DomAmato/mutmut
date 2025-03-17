from .base import BaseMutator

class NumberMutator(BaseMutator):
    def mutate(self):
        suffix = ''
        if self.value.upper().endswith('L'):  # pragma: no cover (python 2 specific)
            suffix = self.value[-1]
            self.value = self.value[:-1]

        if self.value.upper().endswith('J'):
            suffix = self.value[-1]
            self.value = self.value[:-1]

        if self.value.startswith('0o'):
            base = 8
            self.value = self.value[2:]
        elif self.value.startswith('0x'):
            base = 16
            self.value = self.value[2:]
        elif self.value.startswith('0b'):
            base = 2
            self.value = self.value[2:]
        elif self.value.startswith('0') and len(self.value) > 1 and self.value[1] != '.':  # pragma: no cover (python 2 specific)
            base = 8
            self.value = self.value[1:]
        else:
            base = 10

        try:
            parsed = int(self.value, base=base)
        except ValueError:
            # Since it wasn't an int, it must be a float
            parsed = float(self.value)

        result = repr(parsed + 1)
        if not result.endswith(suffix):
            result += suffix
        yield dict(value=result)