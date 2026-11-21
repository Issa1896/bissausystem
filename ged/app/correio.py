"""Notificações pelo correio institucional (SMTP do servidor de e-mail do Estado)."""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid, formatdate

from .config import settings

log = logging.getLogger("ged.correio")


def enviar(para: list[str], assunto: str, texto: str, anexo: tuple[str, bytes] | None = None) -> bool:
    para = [p for p in para if p]
    if not para:
        return False
    msg = EmailMessage()
    msg["From"] = f"GED do Estado <{settings.mail_from}>"
    msg["To"] = ", ".join(para)
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.mail_from.split("@")[-1])
    msg.set_content(texto + "\n\n--\nMensagem automática do Sistema de Gestão Documental do Estado (DEMO).\n")
    if anexo:
        msg.add_attachment(anexo[1], maintype="application", subtype="pdf", filename=anexo[0])
    if not settings.smtp_host:
        log.info("SMTP não configurado; notificação não enviada: %s -> %s", assunto, para)
        return False
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.ehlo()
            if s.has_extn("starttls"):
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE  # certificado autoassinado da demo
                s.starttls(context=ctx)
                s.ehlo()
            s.send_message(msg)
        return True
    except Exception:
        log.exception("Falha ao enviar notificação para %s", para)
        return False
