import datetime
import hashlib
import json
import os

import dpath.util
from pycrdt import Array, Doc, Map


class TelepathicObjectInvalidDocumentError(ValueError):
    """Raise when there is a problem with Document"""


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)


def crdt_wrap(value):
    if isinstance(value, dict) and not isinstance(value, Map):
        return Map({k: crdt_wrap(v) for k, v in value.items()})
    elif isinstance(value, list) and not isinstance(value, Array):
        return Array([crdt_wrap(item) for item in value])
    return value


def unwrap(val):
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
        
    # Handle CRDT Map objects
    if hasattr(val, "to_py") and hasattr(val, "items"):
        try:
            return {k: unwrap(v) for k, v in val.items()}
        except RuntimeError:  # Handle case when document is not integrated
            return val.to_py()
            
    # Handle CRDT Array objects
    if hasattr(val, "to_py") and hasattr(val, "__getitem__") and hasattr(val, "__len__"):
        try:
            return [unwrap(v) for v in val]
        except RuntimeError:  # Handle case when document is not integrated
            return val.to_py()
            
    # Handle standard Python types
    if isinstance(val, (list, tuple)):
        return [unwrap(v) for v in val]
    if isinstance(val, dict):
        return {k: unwrap(v) for k, v in val.items()}
        
    return val


# [TODO] There are a few things I'd like to integrate here:
# * JSON-LD: Add context support for semantic meaning (e.g. some centrally hosted schema?)
# * JSONPath: Adds query capabilities
# * ...?
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
            # Initialize with empty dictionary to support nested field setting
            self._data = crdt_wrap({})

    def _generate_transaction_id(self, entry_data):
        """Generate a deterministic transaction ID from entry data."""
        # Create a copy to avoid modifying the original
        data = entry_data.copy()
        # Remove any existing ID to ensure consistency
        data.pop("transaction_id", None)
        # Create a stable timestamp (without microseconds) for ID generation
        if "timestamp" in data and isinstance(data["timestamp"], datetime.datetime):
            data["timestamp"] = data["timestamp"].replace(microsecond=0).isoformat()
        # Convert to JSON and hash
        data_str = json.dumps(data, sort_keys=True, cls=DateTimeEncoder)
        return hashlib.sha256(data_str.encode()).hexdigest()

    def _log_transaction(self, action, path, value, txn=None, message=""):
        """Log a transaction to the transaction log."""
        timestamp = datetime.datetime.now()
        entry = {
            "timestamp": timestamp,  # Keep full precision for display
            "action": action,
            "path": path,
            "value": value,
            "message": message,
        }
        # Generate ID from the entry data
        entry["transaction_id"] = self._generate_transaction_id(entry)
        self._transaction_log.append(entry)
        return entry

    def get_transaction_log(self):
        """Return the transaction history"""
        return self._transaction_log

    @property
    def data(self):
        return self._data

    def set_field(self, path: str, value, message: str = ""):
        """Set a value at a nested path (e.g. path='foo/bar/baz').
        This always enforces CRDT wrapping for the new value.

        Args:
            path (str): The path where the value should be set
            value: The value to set
            message (str): Optional message describing the change
        """
        # Initialize _data if it's None
        if self._data is None:
            # Create a simple dictionary structure for the path
            parts = path.split('/')
            current = {}
            temp = current
            for part in parts[:-1]:
                temp[part] = {}
                temp = temp[part]
            temp[parts[-1]] = value
            
            # Wrap the entire structure at once
            self._data = crdt_wrap(current)
            
            # Initialize the document
            with self.doc.transaction() as txn:
                self.doc["data"] = self._data
                self._log_transaction("init", "/", current, txn)
            return

        # Get the old value if it exists
        old_value = self.get_field(path)

        # Make the change
        with self.doc.transaction() as txn:
            # Handle array updates
            if isinstance(old_value, list) and isinstance(value, list):
                # For array updates, we'll create a new CRDT array and replace the old one
                crdt_array = crdt_wrap(value)

                # Get the parent object and key
                parts = path.split("/")
                key = parts[-1]
                parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

                if parent_path:
                    # Set the new array at the parent path
                    try:
                        parent = self.get_field(parent_path)
                        parent[key] = crdt_array
                    except KeyError:
                        # Parent doesn't exist, create it
                        parent = {key: crdt_array}
                        self.set_field(parent_path, parent, message)
                else:
                    # If no parent path, update the root
                    self._data = crdt_wrap({key: crdt_array})
            else:
                # For non-array values, use the standard approach
                backing = unwrap(self._data)
                dpath.util.new(backing, path, value)
                self._data = crdt_wrap(backing)

            # Update the document
            self.doc["data"] = self._data

            # Record the transaction
            self._log_transaction(
                "set", path, {"old": old_value, "new": value}, txn, message=message
            )

    def get_field(self, path, default=None):
        # Handle case when _data is None
        if self._data is None:
            return default
            
        # Handle case when _data is not yet integrated into a document
        try:
            if hasattr(self._data, 'doc') and self._data.doc is not None:
                backing = unwrap(self._data)
            else:
                if hasattr(self._data, 'to_py'):
                    backing = self._data.to_py()
                else:
                    backing = self._data
                    
            return dpath.util.get(backing, path)
        except (KeyError, TypeError, RuntimeError):
            return default

    def __repr__(self):
        return f"{self.__class__.__name__}({self.to_dict()!r})"

    def to_dict(self):
        return unwrap(self._data)

    def to_json(self):
        return json.dumps(
            self.to_dict(),
            cls=DateTimeEncoder,
            sort_keys=True,
        )

    def save(self, path):
        """Save this object's collaborative state to a file."""
        # Create a new empty document to get a complete update
        empty_doc = Doc()
        update = self.doc.get_update(empty_doc.get_state())
        
        # Save the update
        with open(path, "wb") as f:
            f.write(update)
            
        print(f"Saved document state to {path} (size: {len(update)} bytes)")

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

        try:
            # Apply the update to the document
            print("\nApplying update to document...")
            doc.apply_update(update)
            print("Successfully applied update")
            
            # Create a new instance with the document
            print("\nCreating TelepathicObject from document...")
            obj = cls._from_doc(doc)
            
            # Verify the document has a 'data' key
            if "data" not in doc:
                print("WARNING: No 'data' key in document after loading!")
                print(f"Document keys: {list(doc.keys())}")
                
            return obj
            
        except Exception as e:
            print(f"ERROR: Failed to load document: {e}")
            print(f"Update data: {update!r}")
            print(f"Document state before error: {doc.get_state()!r}")
            raise

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

        # Initialize the transaction log
        # FIXME PG
        obj._transaction_log = []
        with obj.doc.transaction() as txn:
            obj._log_transaction("init", "/", None, txn)

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

    def serialize_transaction(self, txn):
        """Serialize a transaction to a JSON-serializable dict"""
        if not isinstance(txn, dict):
            # Create a copy to avoid modifying the original
            txn_dict = dict(txn)
            # Strip microseconds for consistent ID generation
            if "timestamp" in txn_dict and isinstance(
                txn_dict["timestamp"], datetime.datetime
            ):
                txn_dict["timestamp"] = txn_dict["timestamp"].replace(microsecond=0)
            txn = {
                "timestamp": (
                    txn_dict["timestamp"].isoformat()
                    if isinstance(txn_dict["timestamp"], datetime.datetime)
                    else txn_dict["timestamp"]
                ),
                "action": txn_dict["action"],
                "path": txn_dict["path"],
                "value": txn_dict["value"],
                "message": txn_dict["message"],
                "transaction_id": txn_dict.get(
                    "transaction_id"
                ),  # Keep existing ID if present
            }
        return txn

    def deserialize_transaction(self, txn_data):
        """Deserialize a transaction from a dict or JSON string"""
        if isinstance(txn_data, str):
            txn_data = json.loads(txn_data)

        # Create a copy to avoid modifying the original
        txn_dict = dict(txn_data)

        # Parse timestamp if it's a string
        if "timestamp" in txn_dict and isinstance(txn_dict["timestamp"], str):
            txn_dict["timestamp"] = datetime.datetime.fromisoformat(
                txn_dict["timestamp"]
            )
        # Strip microseconds for consistent ID generation
        if "timestamp" in txn_dict and isinstance(
            txn_dict["timestamp"], datetime.datetime
        ):
            txn_dict["timestamp"] = txn_dict["timestamp"].replace(microsecond=0)

        # Create a new transaction with the deserialized data
        txn = {
            "timestamp": txn_dict["timestamp"],
            "action": txn_dict["action"],
            "path": txn_dict["path"],
            "value": txn_dict["value"],
            "message": txn_dict["message"],
            "transaction_id": txn_dict.get(
                "transaction_id"
            ),  # Keep existing ID if present
        }
        # If no ID exists, generate one
        if not txn["transaction_id"]:
            txn["transaction_id"] = self._generate_transaction_id(txn)
        return txn

    def save_transaction(self, txn, path):
        """Save a single transaction to a file"""
        txn_data = self.serialize_transaction(txn)
        with open(path, "w") as f:
            json.dump(
                txn_data,
                f,
                indent=2,
                cls=DateTimeEncoder,
                sort_keys=True,
            )

    @staticmethod
    def load_transaction(path):
        """Load a single transaction from a file"""
        with open(path, "r") as f:
            txn_data = json.load(f)
        return txn_data  # Return as dict, can be deserialized with deserialize_transaction if needed

    def apply_transaction(self, txn):
        """Apply a transaction to the current object"""
        txn = self.deserialize_transaction(txn) if isinstance(txn, str) else txn
        
        if txn["action"] == "set":
            new_value = txn["value"]["new"]
            path = txn["path"]
            
            # Handle array updates by replacing the entire array
            if isinstance(new_value, list):
                try:
                    current_value = self.get_field(path)
                    if not isinstance(current_value, list):
                        # If current value is not a list, replace it with the new list
                        with self.doc.transaction() as t:
                            self.set_field(path, new_value.copy(), message=txn.get("message", ""))
                        return
                except KeyError:
                    # Path doesn't exist yet, will be created by set_field
                    pass
            
            # For non-array values or when we need to create a new array
            with self.doc.transaction() as t:
                # Use copy() for mutable values to avoid reference issues
                self.set_field(
                    path, 
                    new_value.copy() if hasattr(new_value, "copy") else new_value, 
                    message=txn.get("message", "")
                )
                
        elif txn["action"] == "init":
            with self.doc.transaction() as t:
                self._data = crdt_wrap(txn["value"])
                self.doc["data"] = self._data
                self._log_transaction(
                    "init",
                    "/",
                    txn["value"],
                    t,
                    message="Initialized data structure...",
                )
        else:
            raise ValueError(f"Unknown transaction action: {txn['action']}")

    @staticmethod
    def default_naming_strategy(txn_data, index):
        """
        Default naming strategy using a 4-digit zero-padded sequential number
        followed by the first 8 characters of the transaction ID.

        Args:
            txn_data (dict): The transaction data
            index (int): The sequential index of the transaction

        Returns:
            str: Formatted filename with counter and transaction ID
        """
        # Ensure the index is stored in the transaction data
        txn_data["sequence_number"] = index
        # Format: 0001_<first-8-chars-of-id>
        return f"{index:04d}_{txn_data.get('transaction_id', '')[:8]}"

    def save_transaction_history(self, directory, naming_strategy=None):
        """
        Save all transactions to individual files in a directory.

        Args:
            directory (str): Directory to save transaction files
            naming_strategy (callable): Function that takes (txn_data, index) and returns a string
                                    for the filename (without extension)
        """
        if naming_strategy is None:
            naming_strategy = self.default_naming_strategy

        os.makedirs(directory, exist_ok=True)

        for i, txn in enumerate(self._transaction_log):
            txn_data = self.serialize_transaction(txn)
            filename_base = naming_strategy(txn_data, i)
            path = os.path.join(directory, f"txn_{filename_base}.json")
            with open(path, "w") as f:
                json.dump(
                    txn_data,
                    f,
                    indent=2,
                    sort_keys=True,
                    cls=DateTimeEncoder,
                )

    @classmethod
    def load_transaction_history(cls, directory, naming_strategy=None):
        """Load all transactions from a directory, sorted by their sequence number.

        Args:
            directory (str): Directory containing transaction files
            naming_strategy (callable): Optional, only used for validation if provided

        Returns:
            list: List of transactions sorted by their sequence number
        """
        transactions = []
        # First pass: load all transactions
        for filename in sorted(os.listdir(directory)):
            if filename.startswith("txn_") and filename.endswith(".json"):
                path = os.path.join(directory, filename)
                try:
                    # Use the class method to load the transaction
                    txn_data = cls.load_transaction(path)

                    # Extract sequence number from filename if not in data
                    if "sequence_number" not in txn_data:
                        parts = filename.split("_")
                        if len(parts) > 1 and parts[1].isdigit():
                            txn_data["sequence_number"] = int(parts[1])

                    transactions.append(txn_data)
                except Exception as e:
                    print(f"Warning: Could not load transaction file {filename}: {e}")

        # Sort transactions by sequence number
        transactions.sort(key=lambda x: x.get("sequence_number", float("inf")))
        return transactions
