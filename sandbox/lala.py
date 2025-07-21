from collections import UserDict

from pycrdt import Array, Map


def crdt_wrap(value):
    if isinstance(value, dict) and not isinstance(value, Map):
        return Map({k: crdt_wrap(v) for k, v in value.items()})
    elif isinstance(value, list) and not isinstance(value, Array):
        return Array([crdt_wrap(item) for item in value])
    return value


class CRDTDict(UserDict):
    def __setitem__(self, key, value):
        super().__setitem__(key, crdt_wrap(value))

    def update(self, *args, **kwargs):
        for k, v in dict(*args, **kwargs).items():
            self[k] = v  # Uses __setitem__ for wrapping


# Usage:
nest = {"user": {"name": "hugin", "tags": ["raven", "thought"]}}
obj = CRDTDict(nest)

print(obj)

obj["user"]["tags"].append("new")
