"""Data classes for Gmail Email Organizer."""

from dataclasses import dataclass, field, asdict
from typing import Optional, List
import json


@dataclass
class EmailSummary:
    id: str
    thread_id: str
    subject: str
    sender: str  # "Name <email>"
    sender_email: str  # just the email address
    date: str
    snippet: str
    labels: List[str] = field(default_factory=list)
    has_unsubscribe: bool = False
    unsubscribe_link: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActionItem:
    email_id: str
    action: str  # "move", "mark-read", "archive", "unsubscribe"
    label_id: Optional[str] = None
    label_name: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActionResult:
    email_id: str
    action: str
    success: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
