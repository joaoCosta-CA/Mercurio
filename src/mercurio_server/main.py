import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast


def _hash(value: str) -> str:
    salt = os.environ.get("MERCURIO_TOKEN_SALT", "development-only-change-me")
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def _seal_phone(phone: str) -> str:
    key = os.environ.get("MERCURIO_PHONE_KEY")
    if key:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise RuntimeError("cryptography é necessário para proteger telefones") from exc
        return "fernet:" + Fernet(key.encode()).encrypt(phone.encode()).decode()
    if os.environ.get("MERCURIO_DEVELOPMENT") == "1":
        return "development:" + phone
    raise RuntimeError("MERCURIO_PHONE_KEY é obrigatório fora do modo de desenvolvimento")


def _open_phone(value: str) -> str:
    if value.startswith("development:") and os.environ.get("MERCURIO_DEVELOPMENT") == "1":
        return value.removeprefix("development:")
    if value.startswith("fernet:"):
        key = os.environ.get("MERCURIO_PHONE_KEY")
        if not key:
            raise RuntimeError("chave de telefone indisponível")
        from cryptography.fernet import Fernet

        return Fernet(key.encode()).decrypt(value.removeprefix("fernet:").encode()).decode()
    raise RuntimeError("telefone armazenado em formato inválido")


class ServerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def migrate(self) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS invite (
                    code_hash TEXT PRIMARY KEY, used_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS enrollment (
                    id TEXT PRIMARY KEY, phone TEXT NOT NULL, consent_version TEXT NOT NULL,
                    verification_hash TEXT NOT NULL, verified_at INTEGER, revoked_at INTEGER,
                    token_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS notification (
                    id TEXT PRIMARY KEY, enrollment_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, provider_id TEXT,
                    state TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_event (
                    enrollment_id TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                """
            )

    def create_invite(self, code: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO invite(code_hash) VALUES(?)", (_hash(code),))

    def enroll(self, invite_code: str, phone: str, consent_version: str) -> tuple[str, str]:
        enrollment_id = secrets.token_urlsafe(18)
        verification = f"{secrets.randbelow(1_000_000):06d}"
        now = int(time.time())
        with self.transaction() as db:
            invite = db.execute(
                "SELECT used_at FROM invite WHERE code_hash=?", (_hash(invite_code),)
            ).fetchone()
            if invite is None or invite["used_at"] is not None:
                raise ValueError("convite inválido ou já utilizado")
            db.execute("UPDATE invite SET used_at=? WHERE code_hash=?", (now, _hash(invite_code)))
            db.execute(
                """INSERT INTO enrollment(id, phone, consent_version, verification_hash)
                VALUES(?, ?, ?, ?)""",
                (enrollment_id, _seal_phone(phone), consent_version, _hash(verification)),
            )
        return enrollment_id, verification

    def verify(self, enrollment_id: str, code: str) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM enrollment WHERE id=?", (enrollment_id,)).fetchone()
            if row is None or row["revoked_at"] is not None:
                raise ValueError("cadastro inexistente ou revogado")
            if not hmac.compare_digest(row["verification_hash"], _hash(code)):
                raise ValueError("código inválido")
            db.execute(
                "UPDATE enrollment SET verified_at=?, token_hash=? WHERE id=?",
                (int(time.time()), _hash(token), enrollment_id),
            )
        return enrollment_id, token

    def authenticate(self, token: str) -> sqlite3.Row | None:
        with self.transaction() as db:
            row = db.execute(
                """SELECT * FROM enrollment WHERE token_hash=?
                AND verified_at IS NOT NULL AND revoked_at IS NULL""",
                (_hash(token),),
            ).fetchone()
            return cast(sqlite3.Row | None, row)

    def revoke(self, enrollment_id: str, token: str) -> bool:
        auth = self.authenticate(token)
        if auth is None or auth["id"] != enrollment_id:
            return False
        with self.transaction() as db:
            db.execute(
                "UPDATE enrollment SET revoked_at=? WHERE id=?",
                (int(time.time()), enrollment_id),
            )
        return True

    def notification(self, enrollment_id: str, key: str) -> tuple[str, bool]:
        notification_id = secrets.token_urlsafe(18)
        with self.transaction() as db:
            old = db.execute(
                "SELECT id FROM notification WHERE idempotency_key=?", (key,)
            ).fetchone()
            if old:
                return str(old["id"]), False
            db.execute(
                """INSERT INTO notification(id, enrollment_id, idempotency_key, state, created_at)
                VALUES(?, ?, ?, 'accepted', ?)""",
                (notification_id, enrollment_id, key, int(time.time())),
            )
        return notification_id, True

    def check_rate_limit(self, enrollment_id: str, limit: int = 20, window: int = 3600) -> bool:
        now = int(time.time())
        with self.transaction() as db:
            db.execute("DELETE FROM rate_event WHERE created_at < ?", (now - window,))
            count = db.execute(
                "SELECT count(*) AS count FROM rate_event WHERE enrollment_id=?",
                (enrollment_id,),
            ).fetchone()["count"]
            if count >= limit:
                return False
            db.execute(
                "INSERT INTO rate_event(enrollment_id, created_at) VALUES(?, ?)",
                (enrollment_id, now),
            )
            return True

    def set_provider(self, notification_id: str, provider_id: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE notification SET provider_id=?, state='sent' WHERE id=?",
                (provider_id, notification_id),
            )

    def update_provider_status(self, provider_id: str, state: str) -> None:
        allowed = {"sent", "delivered", "read", "failed"}
        if state not in allowed:
            return
        with self.transaction() as db:
            db.execute("UPDATE notification SET state=? WHERE provider_id=?", (state, provider_id))


def create_app(store: ServerStore | None = None) -> Any:
    try:
        import httpx
        from fastapi import FastAPI, Header, HTTPException, Request, Response
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("instale o extra server: pip install -e '.[server]'") from exc

    store = store or ServerStore(os.environ.get("MERCURIO_SERVER_DB", "mercurio-server.db"))
    app = FastAPI(title="Mercúrio WhatsApp Gateway", version="1.0")

    class EnrollmentInput(BaseModel):
        invite_code: str
        phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
        consent_version: str = "1"

    class VerifyInput(BaseModel):
        code: str = Field(pattern=r"^[0-9]{6}$")

    class NotificationInput(BaseModel):
        recipient_id: str
        template: str
        variables: dict[str, str]

    def bearer(value: str | None) -> str:
        if not value or not value.startswith("Bearer "):
            raise HTTPException(401, "credencial ausente")
        return value.removeprefix("Bearer ")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        with store.transaction() as db:
            db.execute("SELECT 1")
        return {"status": "ready"}

    @app.post("/v1/enrollments", status_code=201)
    async def enroll(payload: EnrollmentInput) -> dict[str, str]:
        try:
            enrollment_id, code = store.enroll(
                payload.invite_code, payload.phone, payload.consent_version
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Em produção, o código deve ser enviado por template e nunca retornado.
        result = {"id": enrollment_id, "status": "verification_sent"}
        if os.environ.get("MERCURIO_DEVELOPMENT") == "1":
            result["development_code"] = code
        return result

    @app.post("/v1/enrollments/{enrollment_id}/verify")
    async def verify(enrollment_id: str, payload: VerifyInput) -> dict[str, str]:
        try:
            recipient_id, token = store.verify(enrollment_id, payload.code)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"recipient_id": recipient_id, "device_token": token}

    @app.delete("/v1/enrollments/{enrollment_id}", status_code=204)
    async def revoke(enrollment_id: str, authorization: str | None = Header(None)) -> Response:
        if not store.revoke(enrollment_id, bearer(authorization)):
            raise HTTPException(403, "credencial inválida")
        return Response(status_code=204)

    @app.post("/v1/notifications", status_code=202)
    async def notify(
        payload: NotificationInput,
        authorization: str | None = Header(None),
        idempotency_key: str | None = Header(None),
    ) -> dict[str, str]:
        enrollment = store.authenticate(bearer(authorization))
        if enrollment is None or enrollment["id"] != payload.recipient_id:
            raise HTTPException(403, "credencial inválida")
        if not idempotency_key:
            raise HTTPException(400, "Idempotency-Key obrigatório")
        if not store.check_rate_limit(payload.recipient_id):
            raise HTTPException(429, "limite de mensagens excedido")
        notification_id, fresh = store.notification(payload.recipient_id, idempotency_key)
        if fresh and os.environ.get("META_ACCESS_TOKEN"):
            phone_id = os.environ.get("META_PHONE_NUMBER_ID", "")
            response = httpx.post(
                f"https://graph.facebook.com/v21.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {os.environ['META_ACCESS_TOKEN']}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": _open_phone(str(enrollment["phone"])),
                    "type": "template",
                    "template": {
                        "name": payload.template,
                        "language": {"code": "pt_BR"},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [
                                    {"type": "text", "text": value}
                                    for value in payload.variables.values()
                                ],
                            }
                        ],
                    },
                },
                timeout=15,
            )
            if response.is_error:
                raise HTTPException(502, "falha no provedor WhatsApp")
            messages = response.json().get("messages", [])
            if messages:
                store.set_provider(notification_id, str(messages[0]["id"]))
        return {"id": notification_id, "status": "accepted"}

    @app.get("/v1/webhooks/meta")
    async def verify_webhook(request: Request) -> Response:
        params = request.query_params
        if params.get("hub.verify_token") != os.environ.get("META_VERIFY_TOKEN"):
            raise HTTPException(403, "token inválido")
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")

    @app.post("/v1/webhooks/meta")
    async def webhook(
        request: Request, x_hub_signature_256: str | None = Header(None)
    ) -> dict[str, bool]:
        body = await request.body()
        secret = os.environ.get("META_APP_SECRET", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(403, "assinatura inválida")
        payload = json.loads(body)
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for status in change.get("value", {}).get("statuses", []):
                    store.update_provider_status(
                        str(status.get("id", "")), str(status.get("status", ""))
                    )
        return {"accepted": True}

    return app


def run() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("instale o extra server") from exc
    uvicorn.run(create_app(), host="127.0.0.1", port=8080)
