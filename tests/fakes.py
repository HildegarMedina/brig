"""Small test doubles shared across application and interface tests."""

from copy import deepcopy

from brig.errors import BrigError


class MemoryStore:
    def __init__(self, state=None):
        self.state = deepcopy(state)
        self.fail = False

    def load(self):
        return deepcopy(self.state)

    def save(self, state):
        if self.fail:
            raise BrigError("Disk is full")
        self.state = deepcopy(state)
