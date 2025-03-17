from abc import ABC, abstractmethod


class BaseMutator(ABC):
    def __init__(self, context, node, value, children):
        self.context = context
        self.node = node
        self.value = value
        self.children = children
        pass

    @abstractmethod
    def mutate(self):
        pass