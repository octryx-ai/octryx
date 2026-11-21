"""Email channel plugin – send via SMTP, receive via IMAP polling."""

import asyncio
import email as _email_lib
import imaplib
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.services.error_facts import error_text
from app.services.person_log_ref import person_log_ref

from ..core.base import ChannelPlugin

logger = logging.getLogger(__name__)


class EmailPlugin(ChannelPlugin):
    """Send messages via SMTP; receive via IMAP long-poll."""

    INBOUND_POLLING = True

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        super().__init__(plugin_id, config)
        # SMTP
        self.smtp_host: str = config.get("smtp_host", "")
        self.smtp_port: int = int(config.get("smtp_port", 587))
        self.smtp_username: str = config.get("smtp_username", "")
        self.smtp_password: str = config.get("smtp_password", "")
        self.smtp_use_tls: bool = config.get("smtp_use_tls", True)
        self.from_address: str = config.get("from_address", "") or self.smtp_username
        # RBAC fields
        self.require_registered_user: bool = config.get("require_registered_user", False)
        self.allowed_roles: list[str] = config.get("allowed_roles", [])
        self.sender_mappings: dict = {}
        raw = config.get("sender_mappings", "")
        if raw and isinstance(raw, str):
            import json as _json

            self.sender_mappings = _json.loads(raw)
        elif isinstance(raw, dict):
            self.sender_mappings = raw

        # IMAP
        self.imap_enabled: bool = config.get("imap_enabled", True)
        self.imap_host: str = config.get("imap_host", "")
        self.imap_port: int = int(config.get("imap_port", 993))
        self.imap_username: str = config.get("imap_username", "") or self.smtp_username
        self.imap_password: str = config.get("imap_password", "") or self.smtp_password
        self.imap_folder: str = config.get("imap_folder", "INBOX")
        self.poll_interval: float = float(config.get("poll_interval", 30.0))

        self._polling_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue()

    # ---------------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        if not self.smtp_host:
            raise ValueError("smtp_host is required for Email plugin")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._test_smtp)
        logger.info(f"Email plugin: SMTP {self.smtp_host}:{self.smtp_port} OK")
        if self.imap_enabled and self.imap_host and self.inbound_enabled:
            self._polling_task = asyncio.create_task(self._imap_poll_loop())
            logger.info("Email plugin: IMAP polling started")

    async def shutdown(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        logger.info("Email plugin shut down")

    # ---------------------------------------------------------------- messaging

    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        subject = kwargs.get("subject", "Message from Octryx")
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._send_smtp, target, subject, content)
            logger.debug(f"Email sent to {target}")
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", person_log_ref(target), error_text("email_send_failed", exc))
            return False

    async def receive_message(self) -> dict[str, Any] | None:
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ---------------------------------------------------------------- metadata

    def get_plugin_info(self) -> dict[str, Any]:
        return {
            "id": "email",
            "name": "Email",
            "description": "Send and receive messages via SMTP/IMAP email",
            "version": "0.1.0",
            "author": "Octryx",
            "config_fields": [
                {
                    "name": "smtp_host",
                    "type": "string",
                    "required": True,
                    "description": "SMTP server hostname (e.g. smtp.gmail.com)",
                },
                {
                    "name": "smtp_port",
                    "type": "number",
                    "default": 587,
                    "description": "SMTP port – 587 (STARTTLS), 465 (SSL), 25 (plain)",
                },
                {
                    "name": "smtp_username",
                    "type": "string",
                    "required": True,
                    "description": "SMTP login / sender address",
                },
                {
                    "name": "smtp_password",
                    "type": "string",
                    "required": True,
                    "secret": True,
                    "description": "SMTP password or app-password",
                },
                {
                    "name": "smtp_use_tls",
                    "type": "boolean",
                    "default": True,
                    "description": "Use STARTTLS (port 587). Disable for SSL-only (port 465).",
                },
                {
                    "name": "from_address",
                    "type": "string",
                    "description": "From address shown in sent mail (defaults to smtp_username)",
                },
                {
                    "name": "default_target",
                    "type": "string",
                    "default": "",
                    "description": "Default recipient address used for proactive task output delivery",
                },
                {
                    "name": "imap_enabled",
                    "type": "boolean",
                    "default": True,
                    "description": "Enable IMAP polling for incoming messages",
                },
                {"name": "imap_host", "type": "string", "description": "IMAP server hostname (e.g. imap.gmail.com)"},
                {
                    "name": "imap_port",
                    "type": "number",
                    "default": 993,
                    "description": "IMAP port – 993 (SSL), 143 (STARTTLS)",
                },
                {"name": "imap_username", "type": "string", "description": "IMAP username (defaults to smtp_username)"},
                {
                    "name": "imap_password",
                    "type": "string",
                    "secret": True,
                    "description": "IMAP password (defaults to smtp_password)",
                },
                {
                    "name": "imap_folder",
                    "type": "string",
                    "default": "INBOX",
                    "description": "Mailbox folder to monitor",
                },
                {
                    "name": "poll_interval",
                    "type": "number",
                    "default": 30.0,
                    "description": "IMAP polling interval in seconds",
                },
                {
                    "name": "require_registered_user",
                    "type": "boolean",
                    "default": False,
                    "description": "Only respond to senders mapped to an Octryx user",
                },
                {
                    "name": "sender_mappings",
                    "type": "string",
                    "default": "",
                    "description": 'JSON object mapping external sender IDs to platform user IDs, e.g. {"user@example.com": "user-uuid"}',
                },
                {
                    "name": "allowed_roles",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated role names allowed to use this channel (empty = all roles)",
                },
            ],
        }

    # ---------------------------------------------------------------- internals

    def _test_smtp(self) -> None:
        if self.smtp_use_tls:
            srv = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
        else:
            srv = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)
        if self.smtp_username and self.smtp_password:
            srv.login(self.smtp_username, self.smtp_password)
        srv.quit()

    def _send_smtp(self, to_address: str, subject: str, body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = to_address
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if self.smtp_use_tls:
            srv = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
        else:
            srv = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
        if self.smtp_username and self.smtp_password:
            srv.login(self.smtp_username, self.smtp_password)
        srv.sendmail(msg["From"], [to_address], msg.as_string())
        srv.quit()

    async def _imap_poll_loop(self) -> None:
        logger.info("Email IMAP polling loop started")
        while True:
            try:
                loop = asyncio.get_event_loop()
                msgs = await loop.run_in_executor(None, self._fetch_unseen)
                for m in msgs:
                    await self._message_queue.put(m)
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                logger.info("Email IMAP polling loop cancelled")
                break
            except Exception as exc:
                logger.error("IMAP poll error: %s", error_text("imap_poll_failed", exc))
                await asyncio.sleep(min(self.poll_interval * 2, 120))

    def _fetch_unseen(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        try:
            imap_user = self.imap_username or self.smtp_username
            imap_pass = self.imap_password or self.smtp_password
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            mail.login(imap_user, imap_pass)
            mail.select(self.imap_folder)
            status, data = mail.search(None, "UNSEEN")
            if status != "OK":
                mail.logout()
                return messages
            for num in data[0].split():
                status2, msg_data = mail.fetch(num, "(RFC822)")
                if status2 != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                parsed = _email_lib.message_from_bytes(raw_bytes)
                sender = parsed.get("From", "")
                subject = parsed.get("Subject", "")
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                            break
                else:
                    if parsed.get_content_type() == "text/plain":
                        payload = parsed.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")
                mail.store(num, "+FLAGS", "\\Seen")
                messages.append(
                    {
                        "sender_id": sender,
                        "content": body,
                        "target": self.from_address,
                        "timestamp": parsed.get("Date", ""),
                        "subject": subject,
                        "raw": {"from": sender, "subject": subject},
                    }
                )
            mail.logout()
        except Exception as exc:
            logger.error("IMAP fetch error: %s", error_text("imap_fetch_failed", exc))
        return messages
