from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mercurio.config import Paths, Settings
from mercurio.integrations.classroom import FixtureClassroom, GoogleClassroom
from mercurio.integrations.google_auth import has_credentials, load_credentials, login, logout
from mercurio.locking import process_lock
from mercurio.notifications.base import Notifier
from mercurio.notifications.console import ConsoleNotifier
from mercurio.notifications.whatsapp import WhatsAppNotifier
from mercurio.progress import ProgressIndicator
from mercurio.services import deliver_pending, evaluate_reminders, synchronize
from mercurio.storage.sqlite import Database


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mercurio", description="Lembretes do Google Classroom")
    commands = root.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="configurar preferências locais")
    setup.add_argument("--timezone", default="America/Sao_Paulo")
    setup.add_argument("--non-interactive", action="store_true")

    auth = commands.add_parser("auth", help="gerenciar autorização Google")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_commands.add_parser("login")
    auth_login.add_argument("--client-secrets", type=Path, required=True)
    auth_commands.add_parser("status")
    auth_commands.add_parser("logout")

    sync = commands.add_parser("sync", help="sincronizar atividades")
    sync.add_argument("--fixture", type=Path)
    sync.add_argument("--notify", action="store_true")
    sync.add_argument("--channel", choices=("console", "whatsapp", "all"), default="console")

    activities = commands.add_parser("atividades", help="listar atividades")
    activities.add_argument("--json", action="store_true")
    activities.add_argument(
        "--ativas",
        action="store_true",
        help="mostrar apenas atividades pendentes com prazo futuro",
    )

    notices = commands.add_parser("avisos", help="calcular e emitir avisos")
    notices.add_argument("--at", help="instante ISO-8601 para simulação")
    notices.add_argument("--channel", choices=("console", "whatsapp", "all"), default="console")
    notices.add_argument(
        "--historico",
        action="store_true",
        help="mostrar histórico de avisos, sem gerar novos eventos",
    )

    commands.add_parser("status", help="mostrar estado local")
    commands.add_parser("start", help="habilitar timer systemd do usuário")
    commands.add_parser("stop", help="desabilitar timer systemd do usuário")

    channel = commands.add_parser("canal", help="gerenciar canais")
    channel_commands = channel.add_subparsers(dest="channel", required=True)
    whatsapp = channel_commands.add_parser("whatsapp")
    whatsapp_commands = whatsapp.add_subparsers(dest="whatsapp_command", required=True)
    connect = whatsapp_commands.add_parser("conectar")
    connect.add_argument("--base-url", required=True)
    connect.add_argument("--invite-code", required=True)
    connect.add_argument(
        "--phone", required=True, help="telefone em formato E.164, como +5511999999999"
    )
    connect.add_argument("--verification-code", help="código recebido; se omitido, será solicitado")
    whatsapp_commands.add_parser("desconectar")

    data = commands.add_parser("dados", help="gerenciar dados locais")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    erase = data_commands.add_parser("apagar")
    erase.add_argument("--confirmar", required=True)
    return root


def _context() -> tuple[Paths, Settings, Database]:
    paths = Paths()
    paths.ensure()
    settings = Settings.load(paths)
    return paths, settings, Database(paths.database_file)


def _systemctl(*args: str) -> int:
    if shutil.which("systemctl") is None:
        raise RuntimeError("systemctl não está disponível")
    return subprocess.run(["systemctl", "--user", *args], check=False).returncode


def _notify(
    db: Database, settings: Settings, channel: str, now: datetime | None = None
) -> tuple[int, int, int]:
    created = accepted = failed = 0
    channels = ("console", "whatsapp") if channel == "all" else (channel,)
    for selected in channels:
        created += evaluate_reminders(db, settings, now, selected)
        notifier: Notifier
        if selected == "console":
            notifier = ConsoleNotifier(settings.timezone)
        else:
            if not all(
                (
                    settings.whatsapp_base_url,
                    settings.whatsapp_recipient_id,
                    settings.whatsapp_device_token,
                )
            ):
                raise RuntimeError("canal WhatsApp não conectado")
            assert settings.whatsapp_base_url is not None
            assert settings.whatsapp_recipient_id is not None
            assert settings.whatsapp_device_token is not None
            notifier = WhatsAppNotifier(
                settings.whatsapp_base_url,
                settings.whatsapp_recipient_id,
                settings.whatsapp_device_token,
            )
        sent, errors = deliver_pending(db, notifier, channel=selected)
        accepted += sent
        failed += errors
    return created, accepted, failed


def _install_units(paths: Paths) -> None:
    unit_dir = paths.config_dir.parent / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("mercurio") or f"{sys.executable} -m mercurio"
    service = f"""[Unit]
Description=Sincronização Mercúrio
After=network-online.target

[Service]
Type=oneshot
ExecStart={executable} sync --notify
"""
    timer = """[Unit]
Description=Verificação periódica Mercúrio

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
"""
    (unit_dir / "mercurio.service").write_text(service, encoding="utf-8")
    (unit_dir / "mercurio.timer").write_text(timer, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    paths, settings, db = _context()
    db.apply_retention()
    if args.command == "setup":
        settings.timezone = args.timezone
        settings.save(paths)
        db.configure(settings.timezone, settings.reminder_minutes)
        print(f"Mercúrio configurado para {settings.timezone}.")
        return 0
    if args.command == "auth":
        if args.auth_command == "login":
            with ProgressIndicator("Aguardando autorização do Google"):
                login(args.client_secrets, paths)
            print("Conta Google autorizada.")
        elif args.auth_command == "status":
            print("autorizada" if has_credentials(paths) else "não autorizada")
        else:
            logout(paths)
            print("Credencial Google local removida.")
        return 0
    if args.command == "sync":
        with process_lock(paths.lock_file):
            source = (
                FixtureClassroom(args.fixture)
                if args.fixture
                else GoogleClassroom(load_credentials(paths))
            )
            with ProgressIndicator("Sincronizando cursos e atividades"):
                courses, assignments = synchronize(db, source)
            print(f"Sincronizados: {courses} curso(s), {assignments} atividade(s).")
            if args.notify:
                with ProgressIndicator("Processando lembretes"):
                    _, accepted, failed = _notify(db, settings, args.channel)
                print(f"Avisos: {accepted} emitido(s), {failed} falha(s).")
        return 0
    if args.command == "atividades":
        rows = db.assignments()
        if args.ativas:
            active_now = datetime.now(UTC)
            rows = [
                row
                for row in rows
                if row[2].reminder_eligible
                and row[2].due_utc is not None
                and row[2].due_utc > active_now
            ]
        if args.json:
            result = []
            for _, course_name, assignment in rows:
                result.append(
                    {
                        "course": course_name,
                        "title": assignment.title,
                        "due": assignment.due_utc.isoformat() if assignment.due_utc else None,
                        "has_due_time": assignment.has_due_time,
                        "due_date": assignment.due_date.isoformat()
                        if assignment.due_date
                        else None,
                        "state": assignment.submission_state.value,
                        "url": assignment.url,
                    }
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            timezone = ZoneInfo(settings.timezone)
            for _, course_name, assignment in rows:
                if assignment.due_utc:
                    due = assignment.due_utc.astimezone(timezone).strftime("%d/%m/%Y %H:%M")
                elif assignment.due_date:
                    due = assignment.due_date.strftime("%d/%m/%Y") + " (horário indefinido)"
                else:
                    due = "sem prazo definido"
                print(f"{course_name} · {assignment.title} · {due} · {assignment.submission_state}")
        return 0
    if args.command == "avisos":
        if args.historico:
            events = db.event_history()
            if not events:
                print("Nenhum aviso registrado.")
                return 0
            for event in events:
                print(
                    f"{event['state']} · {event['milestone_minutes']} min · "
                    f"{event['course_name']} · {event['title']} · "
                    f"prazo {event['due_utc']} · canal {event['channel']}"
                )
            return 0
        now = datetime.fromisoformat(args.at) if args.at else None
        created, accepted, failed = _notify(db, settings, args.channel, now)
        print(f"{created} novo(s); {accepted} emitido(s); {failed} falha(s).")
        return int(failed > 0)
    if args.command == "status":
        latest = db.latest_sync()
        print(f"Google: {'autorizado' if has_credentials(paths) else 'não autorizado'}")
        sync_status = f"{latest['finished_at']} ({latest['result']})" if latest else "nunca"
        print(f"Última sincronização: {sync_status}")
        print(f"Eventos: {db.status_counts()}")
        return 0
    if args.command == "start":
        _install_units(paths)
        _systemctl("daemon-reload")
        return _systemctl("enable", "--now", "mercurio.timer")
    if args.command == "stop":
        return _systemctl("disable", "--now", "mercurio.timer")
    if args.command == "canal":
        if args.whatsapp_command == "conectar":
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("instale o extra whatsapp-client") from exc
            base_url = args.base_url.rstrip("/")
            try:
                with ProgressIndicator("Conectando ao serviço WhatsApp"):
                    enrollment_response = httpx.post(
                        f"{base_url}/v1/enrollments",
                        json={
                            "invite_code": args.invite_code,
                            "phone": args.phone,
                            "consent_version": "1",
                        },
                        timeout=15,
                    )
                    enrollment_response.raise_for_status()
                    enrollment = enrollment_response.json()
                code = args.verification_code or enrollment.get("development_code")
                if not code:
                    code = input("Código de verificação recebido no WhatsApp: ").strip()
                with ProgressIndicator("Verificando código do WhatsApp"):
                    verification_response = httpx.post(
                        f"{base_url}/v1/enrollments/{enrollment['id']}/verify",
                        json={"code": code},
                        timeout=15,
                    )
                    verification_response.raise_for_status()
                    credential = verification_response.json()
            except Exception as exc:
                raise RuntimeError(f"falha ao conectar WhatsApp: {str(exc)[:200]}") from exc
            settings.whatsapp_base_url = args.base_url
            settings.whatsapp_recipient_id = credential["recipient_id"]
            settings.whatsapp_device_token = credential["device_token"]
            settings.save(paths)
            db.save_consent("whatsapp", credential["recipient_id"], "1")
            print("Canal WhatsApp conectado e consentimento registrado.")
        else:
            if all(
                (
                    settings.whatsapp_base_url,
                    settings.whatsapp_recipient_id,
                    settings.whatsapp_device_token,
                )
            ):
                assert settings.whatsapp_base_url is not None
                assert settings.whatsapp_recipient_id is not None
                assert settings.whatsapp_device_token is not None
                try:
                    import httpx

                    httpx.delete(
                        f"{settings.whatsapp_base_url.rstrip('/')}/v1/enrollments/{settings.whatsapp_recipient_id}",
                        headers={"Authorization": f"Bearer {settings.whatsapp_device_token}"},
                        timeout=15,
                    )
                except Exception:
                    print("aviso: não foi possível confirmar a revogação remota", file=sys.stderr)
            settings.whatsapp_base_url = None
            settings.whatsapp_recipient_id = None
            settings.whatsapp_device_token = None
            settings.save(paths)
            db.revoke_consent("whatsapp")
            print("Canal WhatsApp revogado.")
        return 0
    if args.command == "dados" and args.data_command == "apagar":
        if args.confirmar != "APAGAR":
            raise ValueError("confirmação inválida; use --confirmar APAGAR")
        logout(paths)
        for file in (paths.config_file, paths.database_file):
            if file.exists():
                file.unlink()
        for suffix in ("-wal", "-shm"):
            file = Path(str(paths.database_file) + suffix)
            if file.exists():
                file.unlink()
        if paths.state_dir.exists():
            for file in paths.state_dir.iterdir():
                if file.is_file():
                    file.unlink()
        print("Dados locais do Mercúrio removidos.")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parser().parse_args(argv))
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
