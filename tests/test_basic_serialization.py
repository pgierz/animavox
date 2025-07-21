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


def test_empty_object_to_dict(empty_object):
    """Test serialization of an empty TelepathicObject."""

    assert empty_object.to_dict() == {}


def test_simple_object_to_dict(simple_object):
    """Test serialization of a simple TelepathicObject."""
    assert simple_object.to_dict() == {
        "name": "Test Object",
        "count": 10,
        "tags": ["tag1", "tag2"],
    }


def test_simple_object_to_disk(simple_object, tmp_path):
    """Test serialization of a simple TelepathicObject to disk."""
    simple_object.save_from_scratch(tmp_path / "simple_object.yjs")


def test_simple_object_from_disk(simple_object, tmp_path):
    """Test deserialization of a simple TelepathicObject from disk."""
    simple_object.save_from_scratch(tmp_path / "simple_object.yjs")
    loaded_object = TelepathicObject.load(tmp_path / "simple_object.yjs")
    assert loaded_object.to_dict() == simple_object.to_dict()


def test_simple_object_save_transaction_history(simple_object, tmp_path):
    simple_object.save_transaction_history(tmp_path / "transaction_history")
    assert (tmp_path / "transaction_history").exists()
