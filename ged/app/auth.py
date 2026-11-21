"""Autenticação: Login Único (OIDC/Keycloak) ou modo local para testes."""
import secrets

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Utilizador

ROLES_CONHECIDOS = {"protocolo", "elaboracao", "despacho", "assinatura", "admin"}

oauth = OAuth()
if settings.auth_mode == "oidc":
    oauth.register(
        name="estado",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_metadata_url,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )


class NaoAutenticado(Exception):
    pass


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


async def verificar_csrf(request: Request) -> None:
    form = await request.form()
    esperado = request.session.get("csrf")
    if not esperado or not secrets.compare_digest(str(form.get("csrf", "")), esperado):
        raise HTTPException(status_code=403, detail="Pedido inválido (CSRF). Recarregue a página.")


def sincronizar_utilizador(db: Session, username: str, nome: str, email: str, roles: list[str],
                           cargo: str | None = None, unidade: str | None = None) -> Utilizador:
    u = db.scalars(select(Utilizador).where(Utilizador.username == username)).first()
    if not u:
        u = Utilizador(username=username, nome=nome, email=email)
        db.add(u)
    u.nome, u.email = nome, email
    u.roles = ",".join(sorted(r for r in roles if r in ROLES_CONHECIDOS))
    if cargo is not None:
        u.cargo = cargo
    if unidade is not None:
        u.unidade = unidade
    db.commit()
    return u


def utilizador_atual(request: Request, db: Session = Depends(get_db)) -> Utilizador:
    username = request.session.get("user")
    if not username:
        raise NaoAutenticado()
    u = db.scalars(select(Utilizador).where(Utilizador.username == username)).first()
    if not u:
        request.session.clear()
        raise NaoAutenticado()
    return u


def exigir(role: str):
    def dep(u: Utilizador = Depends(utilizador_atual)) -> Utilizador:
        if not u.tem(role):
            raise HTTPException(status_code=403, detail=f"Ação reservada ao perfil «{role}».")
        return u
    return dep
