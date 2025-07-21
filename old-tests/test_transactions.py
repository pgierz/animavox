import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from animavox.telepathic_objects import (
    TelepathicObject,
    TelepathicObjectTransaction,
)

# Test data
TEST_DATA = {"nested": {"value": 42}, "list": [1, 2, 3], "string": "test"}
import pytest

from animavox.telepathic_objects import TelepathicObject


@pytest.fixture()
def empty_object():
    return TelepathicObject()


@pytest.fixture()
def simple_object():
    obj = TelepathicObject()
    obj.set_field("name", "Test Object")
    obj.set_field("count", 10)
    obj.set_field("tags", ["tag1", "tag2"])
    return obj


# Fixtures
@pytest.fixture
def fresh_object():
    """Provide a fresh TelepathicObject for each test."""
    return TelepathicObject()


@pytest.fixture
def temp_dir():
    """Create a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# Test data for parameterized tests
TRANSACTION_TEST_CASES = [
    ("set", "test/path", {"old": None, "new": 42}, "Test transaction"),
    ("init", "/", TEST_DATA, "Initialize test data"),
    ("set", "deeply/nested/path", {"old": None, "new": "value"}, "Nested path"),
]


# Tests for TelepathicObjectTransaction
class TestTelepathicObjectTransaction:
    @pytest.mark.parametrize(
        "action,path,value,message",
        [
            ("set", "test/path", {"old": None, "new": 42}, "Test transaction"),
            ("init", "/", TEST_DATA, "Init transaction"),
        ],
    )
    def test_creation(self, action, path, value, message):
        """Test transaction creation with various parameters."""
        txn = TelepathicObjectTransaction(
            action=action, path=path, value=value, message=message
        )

        assert txn.action == action
        assert txn.path == path
        assert txn.value == value
        assert txn.message == message
        assert txn.transaction_id is not None
        assert isinstance(txn.timestamp, datetime)
        assert txn.txn is None  # No transaction object passed

    def test_transaction_id_deterministic(self):
        """Same transaction data should produce the same ID."""
        t1 = TelepathicObjectTransaction("set", "test", {"old": None, "new": 1})
        t2 = TelepathicObjectTransaction("set", "test", {"old": None, "new": 1})
        assert t1.transaction_id == t2.transaction_id

        # Different data should produce different IDs
        t3 = TelepathicObjectTransaction("set", "test", {"old": None, "new": 2})
        assert t1.transaction_id != t3.transaction_id

    def test_serialization_roundtrip(self):
        """Test serializing and deserializing a transaction."""
        original = TelepathicObjectTransaction(
            action="set",
            path="test/path",
            value={"old": None, "new": [1, 2, 3]},
            message="Test serialization",
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = TelepathicObjectTransaction.from_dict(data)

        assert original.action == restored.action
        assert original.path == restored.path
        assert original.value == restored.value
        assert original.message == restored.message
        assert original.transaction_id == restored.transaction_id
        assert original.timestamp == restored.timestamp

    def test_serialization_with_timestamp(self):
        """Test serialization with a specific timestamp."""
        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        txn = TelepathicObjectTransaction(
            action="set",
            path="test",
            value={"old": None, "new": 1},
            timestamp=timestamp,
        )

        data = txn.to_dict()
        assert data["timestamp"] == timestamp.isoformat()

        restored = TelepathicObjectTransaction.from_dict(data)
        assert restored.timestamp == timestamp


# Tests for TelepathicObject's transaction handling
class TestTelepathicObjectTransactions:
    @pytest.mark.parametrize("action,path,value,message", TRANSACTION_TEST_CASES)
    def test_apply_transaction(self, fresh_object, action, path, value, message):
        """Test applying different types of transactions."""
        txn = TelepathicObjectTransaction(
            action=action, path=path, value=value, message=message
        )

        result = fresh_object.apply_transaction(txn)

        # Verify the transaction was applied and returned
        assert result == txn

        # Verify the transaction was logged
        log = fresh_object.get_transaction_log()
        assert len(log) == 1
        assert log[0].action == action
        assert log[0].path == path

        # For set operations, verify the value was set
        if action == "set":
            assert fresh_object.get_field(path) == value["new"]
        elif action == "init":
            assert fresh_object.to_dict() == value

    def test_save_and_load_transaction(self, fresh_object, temp_dir):
        """Test saving and loading a transaction to/from a file."""
        txn = TelepathicObjectTransaction(
            action="set",
            path="test/path",
            value={"old": None, "new": "test"},
            message="Test save/load",
        )

        file_path = temp_dir / "test_txn.json"
        fresh_object.save_transaction(txn, str(file_path))

        # Verify the file was created
        assert file_path.exists()

        # Load the transaction
        loaded = fresh_object.load_transaction(str(file_path))

        # Verify the loaded transaction matches the original
        assert txn.action == loaded.action
        assert txn.path == loaded.path
        assert txn.value == loaded.value
        assert txn.message == loaded.message

    def test_transaction_history(self, fresh_object, temp_dir):
        """Test saving and loading transaction history."""
        # Create some transactions
        transactions = [
            TelepathicObjectTransaction("set", f"test/{i}", {"old": None, "new": i})
            for i in range(3)
        ]

        # Apply transactions
        for txn in transactions:
            fresh_object.apply_transaction(txn)

        # Save transaction history
        fresh_object.save_transaction_history(str(temp_dir))

        # Create a new object and load the history
        new_obj = TelepathicObject()
        loaded = new_obj.load_transaction_history(str(temp_dir))

        # Verify we got the same number of transactions back
        assert len(transactions) == len(loaded)

        # Verify the transactions match
        for orig, loaded_txn in zip(transactions, loaded):
            assert orig.action == loaded_txn.action
            assert orig.path == loaded_txn.path
            assert orig.value == loaded_txn.value

    @pytest.mark.parametrize(
        "test_input,expected_exception",
        [
            ({"action": "invalid", "path": "test", "value": {}}, ValueError),
            ({"action": "set", "path": "test", "value": {"new": 1}}, ValueError),
            (
                {"action": "set", "path": "", "value": {"old": None, "new": 1}},
                ValueError,
            ),
        ],
    )
    def test_invalid_transactions(self, fresh_object, test_input, expected_exception):
        """Test that invalid transactions raise appropriate exceptions."""
        txn = TelepathicObjectTransaction(**test_input)
        with pytest.raises(expected_exception):
            fresh_object.apply_transaction(txn)

    def test_transaction_ordering(self, fresh_object):
        """Test that transactions maintain their order."""
        # Apply several transactions
        for i in range(3):
            txn = TelepathicObjectTransaction(
                "set", f"values/{i}", {"old": None, "new": i}, f"Set value {i}"
            )
            fresh_object.apply_transaction(txn)

        # Verify the order is preserved
        log = fresh_object.get_transaction_log()
        assert len(log) == 3

        for i, txn in enumerate(log):
            assert txn.path == f"values/{i}"
            assert txn.value["new"] == i
            assert txn.message == f"Set value {i}"
