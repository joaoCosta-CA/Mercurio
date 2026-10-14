from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mercurio.config import Paths

STUDENT_SUBMISSIONS_SCOPE = (
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly"
)
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    STUDENT_SUBMISSIONS_SCOPE,
]
ALLOWED_GRANTED_SCOPES = {*SCOPES, STUDENT_SUBMISSIONS_SCOPE}


def _validate_granted_scopes(granted: set[str]) -> None:
    unexpected = granted - ALLOWED_GRANTED_SCOPES
    if unexpected:
        raise RuntimeError(
            "o Google devolveu permissões OAuth inesperadas; autorização descartada: "
            + ", ".join(sorted(unexpected))
        )
    courses_scope = "https://www.googleapis.com/auth/classroom.courses.readonly"
    academic_scopes = {STUDENT_SUBMISSIONS_SCOPE}
    if courses_scope not in granted or not granted.intersection(academic_scopes):
        raise RuntimeError("o Google não concedeu todas as permissões de leitura necessárias")


def login(client_secrets: Path, paths: Paths | None = None) -> Any:
    paths = paths or Paths()
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("instale o extra google: pip install -e '.[google]'") from exc
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    # OAuthlib compara literalmente a lista retornada pelo servidor. Mantemos a
    # comparação relaxada apenas durante a troca e validamos o resultado abaixo.
    previous_relax = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        credentials = flow.run_local_server(port=0)
    finally:
        if previous_relax is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous_relax
    granted = set(credentials.scopes or SCOPES)
    _validate_granted_scopes(granted)
    # `Credentials.to_json()` pode preservar os escopos originalmente pedidos,
    # mesmo quando o servidor devolve uma substituição válida. Persistimos os
    # escopos efetivamente concedidos para que a renovação do token não peça a
    # permissão antiga em execuções futuras do timer.
    credential_data = json.loads(credentials.to_json())
    credential_data["scopes"] = sorted(granted)
    payload = json.dumps(credential_data)
    paths.ensure()
    try:
        import keyring

        keyring.set_password("mercurio", "google-oauth", payload)
    except (ImportError, Exception):
        paths.credential_file.write_text(payload, encoding="utf-8")
        paths.credential_file.chmod(0o600)
    return credentials


def load_credentials(paths: Paths | None = None) -> Any:
    paths = paths or Paths()
    payload = None
    try:
        import keyring

        payload = keyring.get_password("mercurio", "google-oauth")
    except (ImportError, Exception):
        pass
    if payload is None and paths.credential_file.exists():
        payload = paths.credential_file.read_text(encoding="utf-8")
    if payload is None:
        raise RuntimeError("conta Google não autorizada; execute `mercurio auth login`")
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise RuntimeError("instale o extra google: pip install -e '.[google]'") from exc
    return Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        json.loads(payload)
    )


def logout(paths: Paths | None = None) -> None:
    paths = paths or Paths()
    payload = None
    try:
        import keyring

        payload = keyring.get_password("mercurio", "google-oauth")
    except Exception:
        pass
    if payload is None and paths.credential_file.exists():
        payload = paths.credential_file.read_text(encoding="utf-8")
    if payload:
        token = json.loads(payload).get("refresh_token") or json.loads(payload).get("token")
        if token:
            try:
                request = Request(
                    "https://oauth2.googleapis.com/revoke",
                    data=urlencode({"token": token}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                urlopen(request, timeout=5).close()
            except OSError:
                pass
    try:
        import keyring

        keyring.delete_password("mercurio", "google-oauth")
    except Exception:
        pass
    if paths.credential_file.exists():
        paths.credential_file.unlink()


def has_credentials(paths: Paths | None = None) -> bool:
    paths = paths or Paths()
    if paths.credential_file.exists():
        return True
    try:
        import keyring

        return keyring.get_password("mercurio", "google-oauth") is not None
    except Exception:
        return False
