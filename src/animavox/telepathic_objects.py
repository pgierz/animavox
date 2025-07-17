import json
import datetime
import dpath.util
from pycrdt import Array, Doc, Map


class TelepathicObjectInvalidDocumentError(ValueError):
    """Raise when there is a problem with Document"""


def crdt_wrap(value):
    if isinstance(value, dict) and not isinstance(value, Map):
        return Map({k: crdt_wrap(v) for k, v in value.items()})
    elif isinstance(value, list) and not isinstance(value, Array):
        return Array([crdt_wrap(item) for item in value])
    return value


def unwrap(val):
    if isinstance(val, Map):
        return {k: unwrap(v) for k, v in val.items()}
    elif isinstance(val, Array):
        return [unwrap(item) for item in val]
    return val


class TelepathicObject:
    def __init__(self, data=None):
        self.doc = Doc()
        self._transaction_log = []  # Store transaction history
        if data is not None:
            self._data = crdt_wrap(data)
            with self.doc.transaction() as txn:
                self.doc["data"] = self._data
                self._log_transaction("init", "/", data, txn)
        else:
            self._data = None

    def _log_transaction(self, action, path, value, txn=None, message=""):
        """Helper method to log transactions

        Args:
            action (str): Type of action (e.g., 'init', 'set')
            path (str): Path that was modified
            value: The value that was set or changed
            txn: The transaction object (optional)
            message (str): Optional user message describing the change
        """
        entry = {
            "timestamp": datetime.datetime.now(),
            "action": action,
            "path": path,
            "value": value,
            "transaction_id": id(txn) if txn else None,
            "message": message,  # Add user message
        }
        self._transaction_log.append(entry)
        return entry

    def get_transaction_log(self):
        """Return the transaction history"""
        return self._transaction_log

    @property
    def data(self):
        return self._data

    def set_field(self, path, value, message=""):
        """
        Set a value at a nested path (e.g. path='foo/bar/baz').
        This always enforces CRDT wrapping for the new value.

        Args:
            path (str): The path where the value should be set
            value: The value to set
            message (str): Optional message describing the change
        """
        # Get the old value before changing it
        old_value = None
        try:
            old_value = self.get_field(path)
        except KeyError:
            pass  # Path didn't exist before

        # Make the change
        backing = unwrap(self._data)  # plain structure
        dpath.util.new(backing, path, value)  # set the value at path
        # Re-wrap the full structure back as CRDTs
        self._data = crdt_wrap(backing)

        # Record the transaction
        with self.doc.transaction() as txn:
            self.doc["data"] = self._data
            self._log_transaction(
                "set", path, {"old": old_value, "new": value}, txn, message=message
            )

    def get_field(self, path, default=None):
        # Same "unwrap" trick, then use dpath.util.get
        backing = unwrap(self._data)
        try:
            return dpath.util.get(backing, path)
        except KeyError:
            return default

    def __repr__(self):
        return f"{self.__class__.__name__}({self.to_dict()!r})"

    def to_dict(self):
        return unwrap(self._data)

    def to_json(self):
        return json.dumps(self.to_dict())

    def save(self, path):
        """Save this object's collaborative state to a file."""
        with open(path, "wb") as f:
            f.write(self.doc.get_state())

    def save_from_scratch(self, path):
        """Dump a full, replayable update file for bootstrap or persistent restore."""
        # Verify the document state before saving
        print("\n=== Verifying document state before saving ===")
        print(f"Document keys: {list(self.doc.keys())}")
        print(f"Data type: {type(self._data)}")
        print(f"Data content: {self._data}")

        # Create a new empty document
        empty_doc = Doc()

        # Get the update that would transform the empty document to the current state
        print("\nGenerating update from empty document...")
        update = self.doc.get_update(empty_doc.get_state())

        # Save the update
        with open(path, "wb") as f:
            f.write(update)

        print(f"\nSaved document update: {update!r}")
        print(f"Document keys after saving: {list(self.doc.keys())}")
        print(f"Data type after saving: {type(self._data)}")
        print(f"Data content after saving: {self._data}")

        # Verify the update can be applied to a new document
        print("\nVerifying update can be loaded...")
        test_doc = Doc()
        try:
            test_doc.apply_update(update)
            print("Successfully applied update to test document")
            print(f"Test document keys: {list(test_doc.keys())}")
            if "data" in test_doc:
                print(f"Test document data: {test_doc['data']}")
            else:
                print("WARNING: 'data' key not found in test document")
        except Exception as e:
            print(f"ERROR: Failed to apply update to test document: {e}")

    @classmethod
    def load(cls, path):
        """Load object from a previously saved state file."""
        print("\n=== Loading saved state ===")

        # Read the saved update
        with open(path, "rb") as f:
            update = f.read()
        print(f"Read {len(update)} bytes from {path}")

        # Create a new empty document
        doc = Doc()
        print(f"Created new document with initial state: {doc.get_state()!r}")

        # Print document contents before applying update
        print("Document contents before update:")
        print(f"Document keys: {list(doc.keys())}")
        print(f"Document state: {doc.get_state()!r}")

        try:
            # Apply the update to the document
            print("\nApplying update to document...")
            doc.apply_update(update)
            print("Successfully applied update")
        except Exception as e:
            print(f"ERROR: Failed to apply update: {e}")
            raise

        # Print document contents after applying update
        print("\nDocument contents after update:")
        print(f"Document keys: {list(doc.keys())}")
        print(f"Document state: {doc.get_state()!r}")

        # Print all document contents
        print("\nDocument contents:")
        for key in doc:
            print(f"- {key}: {doc[key]!r}")

        # Create a new instance with the document
        print("\nCreating TelepathicObject from document...")
        obj = cls._from_doc(doc)

        # Ensure the document has a 'data' key
        if "data" not in doc:
            print("WARNING: No 'data' key in document after loading!")
            print(f"Document keys: {list(doc.keys())}")

            # Create a new empty Map for data and attach it to the document
            with doc.transaction():
                obj._data = Map()
                doc["data"] = obj._data
            print("Created new empty data map")
        else:
            # Get the data from the document
            obj._data = doc["data"]
            print(f"\nLoaded data from document: {obj._data}")
            print(f"Type of loaded data: {type(obj._data)}")

            # If data is None, try to reconstruct from document
            if obj._data is None:
                print("WARNING: Loaded data is None!")
                print("Attempting to reconstruct data from document...")
                with doc.transaction():
                    obj._data = Map()
                    doc["data"] = obj._data  # Make sure it's attached to the document
                    for key in doc:
                        if key != "data":  # Skip the data key itself
                            obj._data[key] = doc[key]
                print("Reconstructed data")

        print("\nFinal object state:")
        print(f"Type: {type(obj)}")
        print(
            f"Data type: {type(obj._data) if hasattr(obj, '_data') else 'No _data attribute'}"
        )

        # Safely print the data content without triggering document access
        if hasattr(obj, "_data") and obj._data is not None:
            try:
                # Try to get a string representation without triggering document access
                data_str = str(obj._data)
                print(f"Data content: {data_str}")
            except Exception as e:
                print(f"Data content: [Error getting string representation: {e}]")
        else:
            print("Data content: None")

        print("\n=== Finished loading ===")
        return obj

    @classmethod
    def _from_doc(cls, doc):
        # Helper to construct directly from Doc instance
        obj = cls.__new__(cls)
        obj.doc = doc

        # Initialize _data to None - it will be set by the caller
        obj._data = None

        return obj

    def get_update(self):
        """Get the latest state update to broadcast to peers."""
        return self.doc.get_update()

    def apply_update(self, update_bytes):
        """Apply an incoming state update from a peer."""
        self.doc.apply_update(update_bytes)
        # Ensure self._data refers to the updated data
        self._data = self.doc["data"]
