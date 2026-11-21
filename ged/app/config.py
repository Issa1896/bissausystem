"""Configuração por variáveis de ambiente (12-factor)."""
import os
import secrets
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "sim"}


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{self.data_dir / 'ged.db'}")
        # URL pública usada nos QR codes e redirecionamentos
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
        self.secret_key = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
        self.cookie_secure = _bool("COOKIE_SECURE", False)

        # Autenticação: "oidc" (Keycloak / Login Único) ou "local" (desenvolvimento e testes)
        self.auth_mode = os.getenv("AUTH_MODE", "local")
        self.oidc_metadata_url = os.getenv(
            "OIDC_METADATA_URL",
            "http://keycloak:8080/realms/estado/.well-known/openid-configuration",
        )
        self.oidc_client_id = os.getenv("OIDC_CLIENT_ID", "ged")
        self.oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "")
        self.oidc_logout_url = os.getenv(
            "OIDC_LOGOUT_URL", "http://localhost:8080/realms/estado/protocol/openid-connect/logout"
        )

        # Correio institucional (notificações)
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "25"))
        self.mail_from = os.getenv("MAIL_FROM", "ged-notificacoes@demo.gov.gw")

        # Identidade institucional
        self.org_sigla = os.getenv("ORG_SIGLA", "DEMO")
        self.org_nome = os.getenv("ORG_NOME", "Ministério de Demonstração")
        self.org_pais = os.getenv("ORG_PAIS", "REPÚBLICA DA GUINÉ-BISSAU")
        self.org_local = os.getenv("ORG_LOCAL", "Bissau")
        self.webmail_url = os.getenv("WEBMAIL_URL", "http://localhost:8081")


settings = Settings()
