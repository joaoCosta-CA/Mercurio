import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from mercurio_server.main import ServerStore, create_app


class ServerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "MERCURIO_DEVELOPMENT": "1",
                "MERCURIO_TOKEN_SALT": "test-salt",
                "META_VERIFY_TOKEN": "verify",
                "META_APP_SECRET": "app-secret",
            },
            clear=False,
        )
        self.environment.start()
        self.store = ServerStore(Path(self.temp.name) / "server.db")
        self.store.create_invite("invite")
        self.app = create_app(self.store)

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def test_health_enrollment_notification_and_revoke(self) -> None:
        asyncio.run(self._health_enrollment_notification_and_revoke())

    async def _health_enrollment_notification_and_revoke(self) -> None:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            self.assertEqual((await client.get("/health/live")).status_code, 200)
            self.assertEqual((await client.get("/health/ready")).status_code, 200)
            enrollment = await client.post(
                "/v1/enrollments",
                json={
                    "invite_code": "invite",
                    "phone": "+5511999999999",
                    "consent_version": "1",
                },
            )
            self.assertEqual(enrollment.status_code, 201)
            details = enrollment.json()
            verification = await client.post(
                f"/v1/enrollments/{details['id']}/verify",
                json={"code": details["development_code"]},
            )
            self.assertEqual(verification.status_code, 200)
            credential = verification.json()
            headers = {
                "Authorization": f"Bearer {credential['device_token']}",
                "Idempotency-Key": "event-1",
            }
            payload = {
                "recipient_id": credential["recipient_id"],
                "template": "lembrete_academico",
                "variables": {"course": "Matemática"},
            }
            first = await client.post("/v1/notifications", headers=headers, json=payload)
            second = await client.post("/v1/notifications", headers=headers, json=payload)
            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.json()["id"], second.json()["id"])
            revoked = await client.delete(
                f"/v1/enrollments/{credential['recipient_id']}",
                headers={"Authorization": f"Bearer {credential['device_token']}"},
            )
            self.assertEqual(revoked.status_code, 204)
            denied = await client.post("/v1/notifications", headers=headers, json=payload)
            self.assertEqual(denied.status_code, 403)

    def test_webhook_verification_and_signature(self) -> None:
        asyncio.run(self._webhook_verification_and_signature())

    async def _webhook_verification_and_signature(self) -> None:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/v1/webhooks/meta",
                params={
                    "hub.verify_token": "verify",
                    "hub.challenge": "challenge",
                },
            )
            self.assertEqual(response.text, "challenge")
            body = json.dumps({"entry": []}).encode()
            signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
            response = await client.post(
                "/v1/webhooks/meta",
                content=body,
                headers={
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(response.status_code, 200)
            denied = await client.post("/v1/webhooks/meta", content=body)
            self.assertEqual(denied.status_code, 403)
