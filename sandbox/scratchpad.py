import json
from collections import UserDict

from pycrdt import Array, Doc, Map


def crdt_wrap(value):
    if isinstance(value, dict) and not isinstance(value, Map):
        return Map({k: crdt_wrap(v) for k, v in value.items()})
    elif isinstance(value, list) and not isinstance(value, Array):
        return Array([crdt_wrap(item) for item in value])
    return value


class TelepathicObject:
    def __init__(self, data):
        self.doc = Doc()
        self.data = crdt_wrap(data)
        self.doc["data"] = self.data

    def __repr__(self):
        return f"{self.__class__.__name__}({self.to_dict()!r})"

    def to_dict(self):
        def unwrap(val):
            if isinstance(val, Map):
                return {k: unwrap(v) for k, v in val.items()}
            elif isinstance(val, Array):
                return [unwrap(item) for item in val]
            return val

        return unwrap(self.data)

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(data)
