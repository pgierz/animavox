import datetime
import hashlib
import json
import os

import dpath.util
from pycrdt import Array, Doc, Map, Transaction


class TelepathicObjectInvalidDocumentError(ValueError):
    """Raise when there is a problem with Document"""


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)


class TelepathicObjectTransaction:
    """Represents a single transaction in a TelepathicObject.

    This class encapsulates all the information about a transaction including
    the action performed, the data changed, and the associated CRDT transaction.
    """

    def __init__(self, action, path, value, txn=None, message=""):
        """Initialize a new transaction.

        Args:
            action (str): The type of action (e.g., 'set', 'init', 'delete')
            path (str): The path where the change occurred
            value: The new value (or dict with 'old' and 'new' for changes)
            txn: The underlying CRDT transaction object
            message (str): Human-readable description of the change
        """
        self.timestamp = datetime.datetime.now().replace(microsecond=0)
        self.action = action
        self.path = path
        self.value = value
        self.txn = txn
        self.message = message
        self.transaction_id = self._generate_id()

    def _generate_id(self):
        """Generate a deterministic ID for this transaction."""
        data = {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "path": self.path,
            "value": self.value,
            "message": self.message,
        }
        data_str = json.dumps(data, sort_keys=True, cls=DateTimeEncoder)
        return hashlib.sha256(data_str.encode()).hexdigest()

    def to_dict(self):
        """Convert the transaction to a dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "path": self.path,
            "value": self.value,
            "message": self.message,
            "transaction_id": self.transaction_id,
            # Note: We don't serialize the txn object here as it's complex
            # and can be reconstructed from the other fields if needed
        }

    @classmethod
    def from_dict(cls, data):
        """Create a transaction from a dictionary."""
        if isinstance(data, str):
            data = json.loads(data)

        # Convert timestamp string back to datetime if needed
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.datetime.fromisoformat(data["timestamp"])

        # Create a new transaction with the deserialized data
        txn = cls.__new__(cls)
        txn.timestamp = data["timestamp"]
        txn.action = data["action"]
        txn.path = data["path"]
        txn.value = data["value"]
        txn.message = data.get("message", "")
        txn.transaction_id = data.get("transaction_id")
        txn.txn = None  # The original transaction object can't be deserialized

        # If transaction_id wasn't in the data, generate it
        if not txn.transaction_id:
            txn.transaction_id = txn._generate_id()

        return txn

    def __repr__(self):
        return f"<TelepathicObjectTransaction {self.action}@{self.path} id={self.transaction_id[:8]}>"


class TransactionEncoder(DateTimeEncoder):
    def default(self, obj):
        if isinstance(obj, Transaction):
            # For pycrdt Transaction objects, return a minimal representation
            return {
                "__type__": "pycrdt.Transaction",
                "state": obj.get_state() if hasattr(obj, "get_state") else str(obj),
            }
        elif isinstance(obj, TelepathicObjectTransaction):
            return obj.to_dict()
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
    if (
        hasattr(val, "to_py")
        and hasattr(val, "__getitem__")
        and hasattr(val, "__len__")
    ):
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

    # Removed _generate_transaction_id as it's now handled by TelepathicObjectTransaction

    def _log_transaction(self, action, path, value, txn=None, message=""):
        """Log a transaction to the transaction log.

        Args:
            action (str): The type of action (e.g., 'set', 'init')
            path (str): The path where the change occurred
            value: The new value or change information
            txn: The underlying CRDT transaction object
            message (str): Human-readable description of the change

        Returns:
            TelepathicObjectTransaction: The created transaction object
        """
        transaction = TelepathicObjectTransaction(
            action=action, path=path, value=value, txn=txn, message=message
        )
        self._transaction_log.append(transaction)
        return transaction

    def get_transaction_log(self):
        """Return the transaction history"""
        return self._transaction_log

    def get_transactions(self):
        return [t.txn for t in self._transaction_log]

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
            parts = path.split("/")
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
            if hasattr(self._data, "doc") and self._data.doc is not None:
                backing = unwrap(self._data)
            else:
                if hasattr(self._data, "to_py"):
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
            cls=TransactionEncoder,
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
        print(f"Update size: {len(update)} bytes")
        print(f"Update type: {type(update)}")

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
                assert test_doc["data"] == self._data
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
            return cls._from_doc(doc)

        except Exception as e:
            print(f"ERROR: Failed to load document: {e}")
            print(f"Update data: {update!r}")
            print(f"Document state before error: {doc.get_state()!r}")
            raise e

    @classmethod
    def _from_doc(cls, doc):
        # Helper to construct directly from Doc instance
        obj = cls.__new__(cls)
        obj.doc = doc
        obj._transaction_log = []

        # Initialize _data from the document
        if "data" in doc and doc["data"] is not None:
            # If the document has data, use it directly
            obj._data = doc["data"]
            print(f"\nLoaded data from document: {obj._data}")
            print(f"Type of loaded data: {type(obj._data)}")
        else:
            print("WARNING: No 'data' key in document or data is None!")
            print(f"Document keys: {list(doc.keys())}")

            # Create a new empty Map for data if it doesn't exist
            with doc.transaction():
                obj._data = Map()
                doc["data"] = obj._data
            print("Created new empty data map")

        # Ensure _data is properly initialized
        if not hasattr(obj, "_data") or obj._data is None:
            with doc.transaction():
                obj._data = Map()
                doc["data"] = obj._data
            print("Initialized empty data map")

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

    def get_update(self):
        """Get the latest state update to broadcast to peers."""
        return self.doc.get_update()

    def apply_update(self, update_bytes):
        """Apply an incoming state update from a peer."""
        self.doc.apply_update(update_bytes)
        # Ensure self._data refers to the updated data
        self._data = self.doc["data"]

    def serialize_transaction(self, txn):
        """Serialize a transaction to a JSON-serializable dict.

        Args:
            txn: A transaction object or dict to serialize

        Returns:
            dict: A JSON-serializable dictionary
        """
        if isinstance(txn, TelepathicObjectTransaction):
            return txn.to_dict()
        elif isinstance(txn, dict):
            # Handle legacy dict format
            return txn
        elif txn is None:
            return None
        else:
            raise ValueError(f"Cannot serialize transaction of type {type(txn)}")

    def deserialize_transaction(self, txn_data):
        """Deserialize a transaction from a dict or JSON string.

        Args:
            txn_data: A JSON string or dict containing transaction data

        Returns:
            TelepathicObjectTransaction: The deserialized transaction
        """
        if isinstance(txn_data, str):
            txn_data = json.loads(txn_data)

        if isinstance(txn_data, dict):
            # Check if this is a legacy format transaction
            if "action" in txn_data and "path" in txn_data:
                return TelepathicObjectTransaction.from_dict(txn_data)

        raise ValueError(f"Invalid transaction data format: {txn_data}")

    def save_transaction(self, txn, path):
        """Save a single transaction to a file.

        Args:
            txn: The transaction to save (can be a dict or TelepathicObjectTransaction)
            path (str): Path to save the transaction to
        """
        if not isinstance(txn, (dict, TelepathicObjectTransaction)):
            txn = self.serialize_transaction(txn)

        with open(path, "w") as f:
            json.dump(
                txn,
                f,
                indent=2,
                cls=TransactionEncoder,
                sort_keys=True,
            )

    @classmethod
    def load_transaction(cls, path):
        """Load a single transaction from a file.

        Args:
            path (str): Path to the transaction file

        Returns:
            TelepathicObjectTransaction: The loaded transaction
        """
        with open(path, "r") as f:
            txn_data = json.load(f)

        # Handle both old and new formats
        if isinstance(txn_data, dict) and "action" in txn_data and "path" in txn_data:
            return TelepathicObjectTransaction.from_dict(txn_data)

        raise ValueError(f"Invalid transaction format in {path}")

    def apply_transaction(self, txn):
        """Apply a transaction to the current object.

        Args:
            txn: A transaction (TelepathicObjectTransaction, dict, or JSON string)

        Returns:
            TelepathicObjectTransaction: The applied transaction

        Raises:
            ValueError: If the transaction is invalid or of unknown type
        """
        # Deserialize if needed
        if isinstance(txn, str):
            txn = self.deserialize_transaction(txn)
        elif isinstance(txn, dict):
            txn = TelepathicObjectTransaction.from_dict(txn)
        elif not isinstance(txn, TelepathicObjectTransaction):
            raise ValueError(f"Unsupported transaction type: {type(txn)}")

        if txn.action == "set":
            if not isinstance(txn.value, dict) or "new" not in txn.value:
                raise ValueError(
                    "Invalid transaction value format. Expected dict with 'new' key."
                )

            new_value = txn.value["new"]
            path = txn.path
            message = txn.message or ""

            # Handle array updates by replacing the entire array
            if isinstance(new_value, list):
                try:
                    current_value = self.get_field(path)
                    if not isinstance(current_value, list):
                        # If current value is not a list, replace it with the new list
                        with self.doc.transaction() as t:
                            self.set_field(path, new_value.copy(), message=message)
                        return txn
                except KeyError:
                    # Path doesn't exist yet, will be created by set_field
                    pass

            # For non-array values or when we need to create a new array
            with self.doc.transaction() as t:
                # Use copy() for mutable values to avoid reference issues
                self.set_field(
                    path,
                    new_value.copy() if hasattr(new_value, "copy") else new_value,
                    message=message,
                )

        elif txn.action == "init":
            with self.doc.transaction() as t:
                self._data = crdt_wrap(txn.value)
                self.doc["data"] = self._data
                self._log_transaction(
                    "init",
                    "/",
                    txn.value,
                    t,
                    message=txn.message or "Initialized data structure...",
                )
        else:
            raise ValueError(f"Unknown transaction action: {txn.action}")

        return txn

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
                    cls=TransactionEncoder,
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

    def pprint_transaction_log(self):
        log = self.get_transaction_log()

        # Set column widths for neatness
        col_widths = {
            "timestamp": 19,  # 'YYYY-MM-DD HH:MM:SS'
            "action": 6,
            "path": 30,
            "message": 20,
            "transaction_id": 18,
        }

        # Header
        lstring = "\n│ LOG:"
        lstring += "\n│"
        for entry in log:
            # Format timestamp
            ts = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            action = entry["action"]
            path = entry["path"]
            message = entry["message"]
            tid = entry["transaction_id"][: col_widths["transaction_id"]]

            # Format the change summary
            val = entry["value"]
            change = f"{val['old']} → {val['new']}"

            # Print the log entry using lines, arrows, etc.
            lstring += "\n│"
            lstring += f"\n├─ * {ts:<{col_widths['timestamp']}} [{action:<{col_widths['action']}}] {path:<{col_widths['path']}}"
            lstring += f"\n│    ↳ {change}  "
            lstring += f"\n│    {message:<{col_widths['message']}} | id: {tid}"
        print(lstring)
        return lstring


# CRDT sync message type constants
CRDT_STATE_REQUEST = "crdt_state_request"
CRDT_STATE_RESPONSE = "crdt_state_response"
CRDT_OPERATION = "crdt_operation"


def create_crdt_state_request(object_id: str):
    """Create a CRDT state request message."""
    from datetime import datetime

    # We'll use a simple dict structure for now since Message class import has issues
    class Message:
        def __init__(self, message_type, content):
            self.message_type = message_type
            self.content = content

        def to_json(self):
            import base64
            import json

            # Handle bytes serialization
            content = self.content.copy()
            for key, value in content.items():
                if isinstance(value, bytes):
                    content[key] = base64.b64encode(value).decode("utf-8")
            return json.dumps({"message_type": self.message_type, "content": content})

    return Message(
        message_type=CRDT_STATE_REQUEST,
        content={"object_id": object_id, "timestamp": datetime.utcnow().isoformat()},
    )


def create_crdt_state_response(object_id: str, state_data: bytes):
    """Create a CRDT state response message."""
    from datetime import datetime

    # We'll use a simple dict structure for now since Message class import has issues
    class Message:
        def __init__(self, message_type, content):
            self.message_type = message_type
            self.content = content

        def to_json(self):
            import base64
            import json

            # Handle bytes serialization
            content = self.content.copy()
            for key, value in content.items():
                if isinstance(value, bytes):
                    content[key] = base64.b64encode(value).decode("utf-8")
            return json.dumps({"message_type": self.message_type, "content": content})

    return Message(
        message_type=CRDT_STATE_RESPONSE,
        content={
            "object_id": object_id,
            "state_data": state_data,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


def create_crdt_operation(object_id: str, operation_data: bytes):
    """Create a CRDT operation message."""
    from datetime import datetime

    # We'll use a simple dict structure for now since Message class import has issues
    class Message:
        def __init__(self, message_type, content):
            self.message_type = message_type
            self.content = content

        def to_json(self):
            import base64
            import json

            # Handle bytes serialization
            content = self.content.copy()
            for key, value in content.items():
                if isinstance(value, bytes):
                    content[key] = base64.b64encode(value).decode("utf-8")
            return json.dumps({"message_type": self.message_type, "content": content})

    return Message(
        message_type=CRDT_OPERATION,
        content={
            "object_id": object_id,
            "operation_data": operation_data,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


class DistributedTelepathicObject(TelepathicObject):
    """A TelepathicObject that automatically synchronizes with peers over a P2P network."""

    def __init__(self, peer, object_id: str, data=None):
        """Initialize a distributed CRDT object.

        Args:
            peer: NetworkPeer instance for P2P communication
            object_id: Unique identifier for this shared object
            data: Initial data for the object (optional)
        """
        super().__init__(data)
        self.peer = peer
        self.object_id = object_id
        # Track last known state for delta calculation
        self._last_state = self.doc.get_state()
        self._setup_sync_handlers()

    def _setup_sync_handlers(self):
        """Set up message handlers for CRDT synchronization."""
        # Register handlers for CRDT message types
        self.peer.on_message(CRDT_STATE_REQUEST, self._handle_crdt_state_request)
        self.peer.on_message(CRDT_STATE_RESPONSE, self._handle_crdt_state_response)
        self.peer.on_message(CRDT_OPERATION, self._handle_crdt_operation)

        # Register peer status change handler for auto-sync
        self.peer.on_peer_status_change(self._handle_peer_status_change)

    async def _handle_crdt_state_request(self, sender_id: str, message):
        """Handle incoming CRDT state request."""
        # Only respond to requests for our object
        if message.content.get("object_id") != self.object_id:
            return

        # Send our current state back to the requester
        state_data = self.get_update()
        response = create_crdt_state_response(self.object_id, state_data)
        await self.peer.send_message(sender_id, response)

    async def _handle_crdt_state_response(self, sender_id: str, message):
        """Handle incoming CRDT state response (full state sync)."""
        # Only process responses for our object
        if message.content.get("object_id") != self.object_id:
            return

        # Apply the full state update
        state_data = message.content.get("state_data")
        if state_data:
            try:
                self.apply_update(state_data)
                # Update our state tracking after applying full state
                self._last_state = self.doc.get_state()
            except BaseException:
                # Handle invalid state data gracefully (including pycrdt panics)
                pass

    async def _handle_crdt_operation(self, sender_id: str, message):
        """Handle incoming CRDT operation (delta)."""
        # Only process operations for our object
        if message.content.get("object_id") != self.object_id:
            return

        # Apply the delta operation
        operation_data = message.content.get("operation_data")
        if operation_data:
            try:
                self.apply_update(operation_data)
                # Update our state tracking after applying the delta
                self._last_state = self.doc.get_state()
            except BaseException:
                # Handle invalid operation data gracefully (including pycrdt panics)
                pass

    async def _handle_peer_status_change(self, peer_id: str, status: str):
        """Handle peer connection status changes."""
        if status == "connected":
            # Request state from newly connected peer
            request = create_crdt_state_request(self.object_id)
            try:
                await self.peer.send_message(peer_id, request)
            except Exception:
                # Handle send failures gracefully
                pass

    async def request_state_from_peer(self, peer_id: str):
        """Request current state from a specific peer."""
        request = create_crdt_state_request(self.object_id)
        await self.peer.send_message(peer_id, request)

    def set_field(self, path: str, value, message: str = ""):
        """Override set_field to broadcast operations to peers.

        This is the synchronous version that maintains compatibility with TelepathicObject.
        For async usage, use set_field_async().
        """
        # Call parent method first
        super().set_field(path, value, message)

        # Schedule the broadcast operation without blocking
        import asyncio

        try:
            # Try to get the current event loop
            loop = asyncio.get_running_loop()
            # Schedule the broadcast as a task
            loop.create_task(self._broadcast_operation())
        except RuntimeError:
            # No event loop running, skip broadcast
            # This is fine for tests or sync-only usage
            pass

    async def set_field_async(self, path: str, value, message: str = ""):
        """Async version of set_field that properly awaits the broadcast."""
        # Call parent method first
        super().set_field(path, value, message)

        # Broadcast the operation to all peers
        await self._broadcast_operation()

    async def _broadcast_operation(self):
        """Helper method to broadcast only the delta (changes since last operation)."""
        # Get current state
        current_state = self.doc.get_state()

        # Calculate delta from last known state
        delta = self.doc.get_update(self._last_state)

        # Update our tracked state
        self._last_state = current_state

        # Only broadcast if there's actually a delta
        if delta:
            operation = create_crdt_operation(self.object_id, delta)
            try:
                await self.peer.broadcast(operation)
            except Exception:
                # Handle broadcast failures gracefully - local update should still succeed
                pass
