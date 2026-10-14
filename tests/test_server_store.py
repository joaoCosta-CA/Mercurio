import os
import tempfile
import unittest
from pathlib import Path

from mercurio_server.main import ServerStore


class ServerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_development = os.environ.get("MERCURIO_DEVELOPMENT")
        os.environ["MERCURIO_DEVELOPMENT"] = "1"
        self.temp = tempfile.TemporaryDirectory()
        self.store = ServerStore(Path(self.temp.name) / "server.db")
        self.store.create_invite("invite")

    def tearDown(self) -> None:
        self.temp.cleanup()
        if self.previous_development is None:
            os.environ.pop("MERCURIO_DEVELOPMENT", None)
        else:
            os.environ["MERCURIO_DEVELOPMENT"] = self.previous_development

    def test_enrollment_auth_idempotency_and_revoke(self) -> None:
        enrollment_id, code = self.store.enroll("invite", "+5511999999999", "1")
        recipient_id, token = self.store.verify(enrollment_id, code)
        self.assertEqual(recipient_id, enrollment_id)
        self.assertIsNotNone(self.store.authenticate(token))
        first, fresh = self.store.notification(enrollment_id, "key")
        second, second_fresh = self.store.notification(enrollment_id, "key")
        self.assertTrue(fresh)
        self.assertFalse(second_fresh)
        self.assertEqual(first, second)
        self.assertTrue(self.store.check_rate_limit(enrollment_id, limit=1))
        self.assertFalse(self.store.check_rate_limit(enrollment_id, limit=1))
        self.assertTrue(self.store.revoke(enrollment_id, token))
        self.assertIsNone(self.store.authenticate(token))

    def test_invite_cannot_be_reused(self) -> None:
        self.store.enroll("invite", "+5511999999999", "1")
        with self.assertRaises(ValueError):
            self.store.enroll("invite", "+5511888888888", "1")
