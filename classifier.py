"""Portable, privacy-safe email classification rules for MailOps Command Center."""

from typing import Dict


class EmailClassifier:
    """Classify common operational mail without embedding account-specific data."""

    LABELS = {
        "finance": "Finance",
        "operations": "Operations",
        "people": "People & Education",
        "travel": "Travel",
        "technology": "Technology",
    }

    IMPORTANT_LABELS = {"Operations", "People & Education", "Travel"}
    UNIMPORTANT_LABELS = {"Finance", "Technology", "archive"}

    ARCHIVE_SENDERS = (
        "noreply", "no-reply", "newsletter", "notifications", "mailer",
        "linkedin", "facebook", "instagram", "x.com", "twitter",
    )
    ARCHIVE_SUBJECTS = (
        "unsubscribe", "weekly digest", "monthly digest", "special offer",
        "sale", "promotion", "your order has shipped",
    )

    def is_important(self, email: Dict, label: str) -> bool:
        """Return a conservative importance signal for the review interface."""
        if label in self.IMPORTANT_LABELS:
            return True
        if label in self.UNIMPORTANT_LABELS:
            return False
        return "IMPORTANT" in email.get("labels", [])

    def classify(self, email: Dict) -> Dict:
        """Return a label suggestion, confidence level, and whether AI review is useful."""
        sender = self._combined_sender(email)
        subject = email.get("subject", "").lower()
        snippet = email.get("snippet", "").lower()
        text = f"{sender} {subject} {snippet}"

        if self._matches(text, self.ARCHIVE_SENDERS) or self._matches(subject, self.ARCHIVE_SUBJECTS):
            return self._result("archive", "high", "Matches a low-priority notification or promotion rule.")

        if self._matches(text, ("invoice", "receipt", "statement", "payment", "billing", "transaction", "expense")):
            return self._result(self.LABELS["finance"], "high", "Matches a finance or receipt rule.")

        if self._matches(text, ("contract", "project", "meeting", "proposal", "support ticket", "account manager")):
            return self._result(self.LABELS["operations"], "high", "Matches an operations rule.")

        if self._matches(text, ("school", "student", "parent", "teacher", "training", "enrollment")):
            return self._result(self.LABELS["people"], "high", "Matches a people or education rule.")

        if self._matches(text, ("flight", "airline", "hotel", "reservation", "itinerary", "rental car")):
            return self._result(self.LABELS["travel"], "high", "Matches a travel rule.")

        if self._matches(text, ("github", "deployment", "security alert", "api", "software", "product update")):
            return self._result(self.LABELS["technology"], "high", "Matches a technology rule.")

        return self._result("inbox", "low", "No portable rule matched; review before filing.", needs_claude=True)

    @staticmethod
    def _combined_sender(email: Dict) -> str:
        return f"{email.get('sender', '')} {email.get('sender_email', '')}".lower()

    @staticmethod
    def _matches(text: str, keywords) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _result(label: str, confidence: str, reason: str, needs_claude: bool = False) -> Dict:
        return {
            "label": label,
            "confidence": confidence,
            "reason": reason,
            "needs_claude": needs_claude,
        }
