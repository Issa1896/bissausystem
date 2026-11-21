from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Estado:
    RASCUNHO = "rascunho"
    SUBMETIDO = "submetido"          # aguarda registo no protocolo
    PROTOCOLADO = "protocolado"      # aguarda despacho
    DESPACHADO = "despachado"        # aguarda assinatura
    ASSINADO = "assinado"

    ROTULOS = {
        RASCUNHO: "Rascunho",
        SUBMETIDO: "Submetido · aguarda protocolo",
        PROTOCOLADO: "Protocolado · aguarda despacho",
        DESPACHADO: "Despachado · aguarda assinatura",
        ASSINADO: "Assinado",
    }


class Utilizador(Base):
    __tablename__ = "utilizadores"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    nome: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    cargo: Mapped[str] = mapped_column(String(200), default="")
    unidade: Mapped[str] = mapped_column(String(200), default="")
    roles: Mapped[str] = mapped_column(String(300), default="")

    def tem(self, role: str) -> bool:
        return role in self.roles.split(",")


class Sequencia(Base):
    """Numeração única de protocolo por ano (bloqueio de linha em PostgreSQL)."""
    __tablename__ = "sequencias"
    __table_args__ = (UniqueConstraint("sigla", "ano"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sigla: Mapped[str] = mapped_column(String(20))
    ano: Mapped[int] = mapped_column(Integer)
    ultimo: Mapped[int] = mapped_column(Integer, default=0)


class Documento(Base):
    __tablename__ = "documentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(50), default="Ofício")
    numero: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    assunto: Mapped[str] = mapped_column(String(300))
    destinatario: Mapped[str] = mapped_column(String(300))
    destinatario_email: Mapped[str] = mapped_column(String(200), default="")
    corpo: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(30), default=Estado.RASCUNHO)
    classificacao: Mapped[str] = mapped_column(String(100), default="")

    autor_id: Mapped[int] = mapped_column(ForeignKey("utilizadores.id"))
    protocolado_por_id: Mapped[int | None] = mapped_column(ForeignKey("utilizadores.id"), nullable=True)
    protocolado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    despacho_texto: Mapped[str] = mapped_column(Text, default="")
    despachante_id: Mapped[int | None] = mapped_column(ForeignKey("utilizadores.id"), nullable=True)
    despachado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signatario_id: Mapped[int | None] = mapped_column(ForeignKey("utilizadores.id"), nullable=True)
    assinado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    codigo_verificacao: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(300), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)

    autor: Mapped[Utilizador] = relationship(foreign_keys=[autor_id])
    protocolado_por: Mapped[Utilizador | None] = relationship(foreign_keys=[protocolado_por_id])
    despachante: Mapped[Utilizador | None] = relationship(foreign_keys=[despachante_id])
    signatario: Mapped[Utilizador | None] = relationship(foreign_keys=[signatario_id])
    eventos: Mapped[list["Evento"]] = relationship(back_populates="documento", order_by="Evento.id")

    @property
    def estado_rotulo(self) -> str:
        return Estado.ROTULOS.get(self.estado, self.estado)


class Evento(Base):
    """Trilha de auditoria encadeada por hash (deteta adulteração do histórico)."""
    __tablename__ = "eventos"
    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos.id"), nullable=True)
    utilizador: Mapped[str] = mapped_column(String(100))
    acao: Mapped[str] = mapped_column(String(50))
    detalhe: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    hash_anterior: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    documento: Mapped[Documento | None] = relationship(back_populates="eventos")
