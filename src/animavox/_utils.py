# def _get_info(obj):
#     info = {
#         "id": id(obj),
#         "type": type(obj),
#         "data": obj.data,
#         "type(data)": type(obj.data),
#     }
#     return info


def _get_info(obj_or_data):
    # Handle your top-level TelepathicObject specially
    if hasattr(obj_or_data, "_data"):
        return {
            "id": id(obj_or_data),
            "type": type(obj_or_data),
            "data": _get_info(obj_or_data.data),
            "type(data)": type(obj_or_data.data),
            "json": obj_or_data.to_json(),
        }
    # Handle pycrdt.Map or dict-like
    elif hasattr(obj_or_data, "items") and hasattr(obj_or_data, "__getitem__"):
        return {
            "type": type(obj_or_data),
            "items": {k: _get_info(v) for k, v in obj_or_data.items()},
        }
    # Handle pycrdt.Array, list, or tuple-like
    elif hasattr(obj_or_data, "__iter__") and not isinstance(
        obj_or_data, (str, bytes, dict)
    ):
        return {"type": type(obj_or_data), "items": [_get_info(v) for v in obj_or_data]}
    else:
        # Always show the value and its type for primitives
        return {"type": type(obj_or_data), "value": obj_or_data}
