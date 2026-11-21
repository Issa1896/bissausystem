import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Evento, agora

GENESIS = "0" * 64


def _calc(ev: Evento) -> str:
    payload = json.dumps(
        {
            "documento_id": ev.documento_id,
            "utilizador": ev.utilizador,
            "acao": ev.acao,
            "detalhe": ev.detalhe,
            "ip": ev.ip,
            "criado_em": ev.criado_em.replace(tzinfo=None).isoformat(timespec="microseconds"),
            "hash_anterior": ev.hash_anterior,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def registar(db: Session, utilizador: str, acao: str, detalhe: str = "", documento_id=None, ip: str = "") -> Evento:
    ultimo = db.scalars(select(Evento).order_by(Evento.id.desc()).limit(1).with_for_update()).first()
    ev = Evento(
        documento_id=documento_id,
        utilizador=utilizador,
        acao=acao,
        detalhe=detalhe,
        ip=ip,
        criado_em=agora(),
        hash_anterior=ultimo.hash if ultimo else GENESIS,
    )
    ev.hash = _calc(ev)
    db.add(ev)
    return ev


def verificar_cadeia(db: Session) -> tuple[bool, int, int | None]:
    """Devolve (íntegra, total, id do primeiro evento inválido)."""
    anterior = GENESIS
    total = 0
    for ev in db.scalars(select(Evento).order_by(Evento.id)):
        total += 1
        if ev.hash_anterior != anterior or _calc(ev) != ev.hash:
            return False, total, ev.id
        anterior = ev.hash
    return True, total, None
