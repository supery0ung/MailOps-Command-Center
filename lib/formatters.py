"""Output formatting - all CLI output goes through here."""

import json
from typing import List
from models import EmailSummary, ActionResult


def to_json(data) -> str:
    """Serialize to JSON. Handles dataclasses via to_dict()."""
    if isinstance(data, list):
        serializable = [item.to_dict() if hasattr(item, 'to_dict') else item for item in data]
    elif hasattr(data, 'to_dict'):
        serializable = data.to_dict()
    else:
        serializable = data
    return json.dumps(serializable, ensure_ascii=False, indent=2)
