#!/usr/bin/env python3
"""Gera a configuração da demo a partir do diretório único (ged/app/diretorio.py):
- infra/keycloak/realm-estado.json  (Login Único: perfis, utilizadores, clientes OIDC, políticas)
- infra/mailserver/config/postfix-accounts.cf  (caixas de correio)

Uso: python3 scripts/gerar_config.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ged"))
from app.diretorio import DOMINIO, UTILIZADORES  # noqa: E402

SENHA_DEMO = os.getenv("SENHA_DEMO", "Demo#2026")
GED_URL = os.getenv("GED_URL", "http://localhost:8000")
WEBMAIL_URL = os.getenv("WEBMAIL_URL", "http://localhost:8081")

PERFIS = {
    "protocolo": "Registo de entrada e saída (protocolo)",
    "elaboracao": "Elaboração de documentos",
    "despacho": "Despacho de dirigente",
    "assinatura": "Assinatura de documentos oficiais",
    "admin": "Administração e auditoria",
}

mapper_perfis = {
    "name": "perfis-ged", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-realm-role-mapper",
    "config": {"claim.name": "roles", "multivalued": "true", "jsonType.label": "String", "id.token.claim": "true",
               "access.token.claim": "true", "userinfo.token.claim": "true", "introspection.token.claim": "true"},
}


def cliente(client_id, nome, url, redirect, mappers=(), pkce=True):
    return {
        "clientId": client_id, "name": nome, "enabled": True, "protocol": "openid-connect", "publicClient": False,
        "clientAuthenticatorType": "client-secret", "secret": f"{client_id}-segredo-demo-TROCAR",
        "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
        "redirectUris": [redirect], "webOrigins": [url], "rootUrl": url, "baseUrl": "/",
        "attributes": {"post.logout.redirect.uris": f"{url}/*",
                       **({"pkce.code.challenge.method": "S256"} if pkce else {})},
        "protocolMappers": list(mappers),
    }


utilizadores = []
for u in UTILIZADORES:
    primeiro, *resto = u["nome"].split()
    utilizadores.append({
        "username": u["username"], "enabled": True, "emailVerified": True,
        "firstName": primeiro, "lastName": " ".join(resto), "email": u["email"],
        "credentials": [{"type": "password", "value": SENHA_DEMO, "temporary": False}],
        "realmRoles": ["default-roles-estado", *u["roles"]],
    })

realm = {
    "realm": "estado", "displayName": "Login Único do Estado — DEMO", "enabled": True,
    "internationalizationEnabled": True, "supportedLocales": ["pt-PT", "pt-BR", "en", "fr"], "defaultLocale": "pt-PT",
    "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False, "resetPasswordAllowed": True,
    "sslRequired": "external",
    # proteção contra força bruta e política de senhas
    "bruteForceProtected": True, "failureFactor": 5, "waitIncrementSeconds": 60, "maxFailureWaitSeconds": 900,
    "passwordPolicy": "length(8) and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1) "
                      "and notUsername(undefined) and passwordHistory(5)",
    # MFA (TOTP) — ativado por utilizador ou tornado obrigatório por perfil
    "otpPolicyType": "totp", "otpPolicyAlgorithm": "HmacSHA1", "otpPolicyDigits": 6, "otpPolicyPeriod": 30,
    "ssoSessionIdleTimeout": 1800, "ssoSessionMaxLifespan": 36000, "accessTokenLifespan": 300,
    "eventsEnabled": True, "adminEventsEnabled": True, "adminEventsDetailsEnabled": True,
    "enabledEventTypes": ["LOGIN", "LOGIN_ERROR", "LOGOUT", "CODE_TO_TOKEN", "UPDATE_TOTP", "REMOVE_TOTP",
                          "UPDATE_PASSWORD"],
    "roles": {"realm": [{"name": k, "description": v} for k, v in PERFIS.items()]},
    "clients": [
        cliente("ged", "Gestão Documental (GED)", GED_URL, f"{GED_URL}/auth/callback", [mapper_perfis]),
        # Roundcube 1.6 não suporta PKCE
        cliente("webmail", "Correio Institucional (Webmail)", WEBMAIL_URL, f"{WEBMAIL_URL}/*", pkce=False),
    ],
    "users": utilizadores,
}
destino = RAIZ / "infra/keycloak/realm-estado.json"
destino.write_text(json.dumps(realm, ensure_ascii=False, indent=2) + "\n")
print("✔", destino.relative_to(RAIZ))

contas = [u["email"] for u in UTILIZADORES] + [f"gabinete.financas@{DOMINIO}", f"ged-notificacoes@{DOMINIO}"]
linhas = []
for c in contas:
    sal = c.split("@")[0].replace(".", "")[:16]
    h = subprocess.check_output(["openssl", "passwd", "-6", "-salt", sal, SENHA_DEMO]).decode().strip()
    linhas.append(f"{c}|{{SHA512-CRYPT}}{h}")
destino = RAIZ / "infra/mailserver/config/postfix-accounts.cf"
destino.parent.mkdir(parents=True, exist_ok=True)
destino.write_text("\n".join(linhas) + "\n")
print("✔", destino.relative_to(RAIZ), f"({len(contas)} caixas)")
