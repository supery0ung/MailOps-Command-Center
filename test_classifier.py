#!/usr/bin/env python3
"""Smoke tests for the portable MailOps classifier rules."""

from classifier import EmailClassifier


TEST_CASES = [
    ({"sender": "billing@example.test", "subject": "Invoice available", "snippet": "Payment due"}, "Finance"),
    ({"sender": "projects@example.test", "subject": "Project meeting", "snippet": "Agenda attached"}, "Operations"),
    ({"sender": "school@example.test", "subject": "Student enrollment", "snippet": "Training information"}, "People & Education"),
    ({"sender": "travel@example.test", "subject": "Flight itinerary", "snippet": "Reservation confirmed"}, "Travel"),
    ({"sender": "security@example.test", "subject": "Security alert", "snippet": "Software update"}, "Technology"),
    ({"sender": "newsletter@example.test", "subject": "Weekly digest", "snippet": "Latest updates"}, "archive"),
]


def main():
    classifier = EmailClassifier()
    for email, expected_label in TEST_CASES:
        result = classifier.classify(email)
        assert result["label"] == expected_label, (email, result)
    print(f"Passed {len(TEST_CASES)} portable classifier checks.")


if __name__ == "__main__":
    main()
