import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import auditoria, correio, diretorio, pki
from .auth import (NaoAutenticado, csrf_token, exigir, oauth, sincronizar_utilizador,
                   utilizador_atual, verificar_csrf)
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .documentos_pdf import (assinar_pdf, data_extenso, gerar_pdf, sha256, url_verificacao,
                             validar_pdf, TZ)
from .models import Documento, Estado, Sequencia, Utilizador, agora

logging.basicConfig(level=logging.INFO)
BASE = Path(__file__).resolve().parent
PDF_DIR = settings.data_dir / "documentos"
PDF_DIR.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def ciclo_vida(_app):
    iniciar()
    yield


app = FastAPI(title="GED do Estado — Demonstração", docs_url=None, redoc_url=None, lifespan=ciclo_vida)
app.add_middleware(
    SessionMiddleware, secret_key=settings.secret_key, session_cookie="ged_sessao",
    same_site="lax", https_only=settings.cookie_secure, max_age=8 * 3600,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(settings=settings, Estado=Estado)
templates.env.filters["dt"] = lambda d: d.astimezone(TZ).strftime("%d/%m/%Y %H:%M") if d else "—"


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "form-action 'self' " + settings.base_url.split("/")[0] + "//*; frame-ancestors 'none'"
    )
    if settings.cookie_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.exception_handler(NaoAutenticado)
async def _nao_autenticado(request: Request, exc: NaoAutenticado):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(HTTPException)
async def _erro_http(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        request, "erro.html", {"codigo": exc.status_code, "mensagem": exc.detail, "user": None},
        status_code=exc.status_code,
    )


def iniciar() -> None:
    Base.metadata.create_all(engine)
    pki.garantir_acs()
    with SessionLocal() as db:
        for u in diretorio.UTILIZADORES:
            existe = db.scalars(select(Utilizador).where(Utilizador.username == u["username"])).first()
            if not existe:
                sincronizar_utilizador(db, u["username"], u["nome"], u["email"], u["roles"], u["cargo"], u["unidade"])


def ctx(request: Request, user: Utilizador | None, **kw) -> dict:
    return {"user": user, "csrf": csrf_token(request), **kw}


def ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "").split(",")[0]


def voltar(doc_id: int | None = None, msg: str | None = None) -> RedirectResponse:
    url = f"/documentos/{doc_id}" if doc_id else "/"
    if msg:
        url += f"?msg={msg}"
    return RedirectResponse(url, status_code=303)


def texto(valor: str) -> str:
    return valor.replace("\r\n", "\n").replace("\r", "\n").strip()


def obter_doc(db: Session, doc_id: int) -> Documento:
    doc = db.get(Documento, doc_id)
    if not doc:
        raise HTTPException(404, "Documento não encontrado.")
    return doc


# ---------------------------------------------------------------- autenticação
@app.get("/login", response_class=HTMLResponse)
async def login(request: Request, db: Session = Depends(get_db)):
    if settings.auth_mode == "oidc":
        return await oauth.estado.authorize_redirect(request, f"{settings.base_url}/auth/callback")
    users = db.scalars(select(Utilizador).order_by(Utilizador.id)).all()
    return templates.TemplateResponse(request, "login_local.html", ctx(request, None, utilizadores=users))


@app.post("/login/local", dependencies=[Depends(verificar_csrf)])
async def login_local(request: Request, username: str = Form(...), db: Session = Depends(get_db)):
    if settings.auth_mode != "local":
        raise HTTPException(404, "Indisponível.")
    u = db.scalars(select(Utilizador).where(Utilizador.username == username)).first()
    if not u:
        raise HTTPException(400, "Utilizador desconhecido.")
    request.session.clear()
    request.session["user"] = u.username
    auditoria.registar(db, u.username, "login", "modo local", ip=ip(request))
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    token = await oauth.estado.authorize_access_token(request)
    info = token.get("userinfo") or {}
    username = info.get("preferred_username")
    if not username:
        raise HTTPException(401, "Resposta de autenticação inválida.")
    base = next((d for d in diretorio.UTILIZADORES if d["username"] == username), {})
    u = sincronizar_utilizador(
        db, username, info.get("name") or username, info.get("email", ""), info.get("roles", []),
        info.get("cargo") or base.get("cargo"), info.get("unidade") or base.get("unidade"),
    )
    request.session.clear()
    request.session["user"] = u.username
    request.session["id_token"] = token.get("id_token")
    auditoria.registar(db, u.username, "login", "Login Único (OIDC)", ip=ip(request))
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    id_token = request.session.get("id_token")
    request.session.clear()
    if settings.auth_mode == "oidc" and id_token:
        from urllib.parse import urlencode
        q = urlencode({"id_token_hint": id_token, "post_logout_redirect_uri": settings.base_url + "/"})
        return RedirectResponse(f"{settings.oidc_logout_url}?{q}", status_code=303)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- painel
@app.get("/", response_class=HTMLResponse)
def painel(request: Request, db: Session = Depends(get_db)):
    try:
        user = utilizador_atual(request, db)
    except NaoAutenticado:
        return templates.TemplateResponse(request, "inicio.html", ctx(request, None))
    q = select(Documento).order_by(Documento.atualizado_em.desc())
    conds = []
    if user.tem("protocolo"):
        conds.append(Documento.estado == Estado.SUBMETIDO)
    if user.tem("despacho"):
        conds.append(Documento.estado == Estado.PROTOCOLADO)
    if user.tem("assinatura"):
        conds.append((Documento.estado == Estado.DESPACHADO) & (Documento.signatario_id == user.id))
    if user.tem("elaboracao"):
        conds.append((Documento.estado == Estado.RASCUNHO) & (Documento.autor_id == user.id))
    tarefas = db.scalars(q.where(or_(*conds))).all() if conds else []
    todos = db.scalars(q.limit(50)).all()
    return templates.TemplateResponse(request, "painel.html", ctx(request, user, tarefas=tarefas, todos=todos))


# ---------------------------------------------------------------- documentos
@app.get("/documentos/novo", response_class=HTMLResponse)
def novo(request: Request, user: Utilizador = Depends(exigir("elaboracao"))):
    return templates.TemplateResponse(request, "novo.html", ctx(request, user, caixa_externa=diretorio.CAIXA_EXTERNA))


@app.post("/documentos", dependencies=[Depends(verificar_csrf)])
def criar(request: Request, assunto: str = Form(..., max_length=300), destinatario: str = Form(..., max_length=300),
          destinatario_email: str = Form("", max_length=200), corpo: str = Form(..., max_length=20000),
          classificacao: str = Form("", max_length=100),
          user: Utilizador = Depends(exigir("elaboracao")), db: Session = Depends(get_db)):
    doc = Documento(assunto=assunto.strip(), destinatario=destinatario.strip(),
                    destinatario_email=destinatario_email.strip(), corpo=texto(corpo),
                    classificacao=classificacao.strip(), autor_id=user.id)
    db.add(doc)
    db.flush()
    auditoria.registar(db, user.username, "criar", f"Ofício «{doc.assunto}» criado", doc.id, ip(request))
    db.commit()
    return voltar(doc.id, "criado")


@app.get("/documentos/{doc_id}", response_class=HTMLResponse)
def detalhe(doc_id: int, request: Request, user: Utilizador = Depends(utilizador_atual),
            db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    signatarios = [u for u in db.scalars(select(Utilizador).order_by(Utilizador.nome)) if u.tem("assinatura")]
    return templates.TemplateResponse(request, "documento.html", ctx(
        request, user, doc=doc, signatarios=signatarios, msg=request.query_params.get("msg"),
        url_verif=url_verificacao(doc.codigo_verificacao) if doc.codigo_verificacao else None))


@app.post("/documentos/{doc_id}/submeter", dependencies=[Depends(verificar_csrf)])
def submeter(doc_id: int, request: Request, user: Utilizador = Depends(exigir("elaboracao")),
             db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if doc.estado != Estado.RASCUNHO or doc.autor_id != user.id:
        raise HTTPException(403, "Só o autor pode submeter um rascunho.")
    doc.estado = Estado.SUBMETIDO
    auditoria.registar(db, user.username, "submeter", "Submetido ao protocolo", doc.id, ip(request))
    db.commit()
    protocolo = [u.email for u in db.scalars(select(Utilizador)) if u.tem("protocolo")]
    correio.enviar(protocolo, f"[GED] Novo documento para protocolar: {doc.assunto}",
                   f"{user.nome} submeteu o {doc.tipo.lower()} «{doc.assunto}» para registo.\n\n"
                   f"Abrir: {settings.base_url}/documentos/{doc.id}")
    return voltar(doc.id, "submetido")


@app.post("/documentos/{doc_id}/protocolar", dependencies=[Depends(verificar_csrf)])
def protocolar(doc_id: int, request: Request, user: Utilizador = Depends(exigir("protocolo")),
               db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if doc.estado != Estado.SUBMETIDO:
        raise HTTPException(409, "O documento não está em estado de ser protocolado.")
    if not doc.numero:
        ano = agora().astimezone(TZ).year
        seq = db.scalars(select(Sequencia).where(Sequencia.sigla == settings.org_sigla, Sequencia.ano == ano)
                         .with_for_update()).first()
        if not seq:
            seq = Sequencia(sigla=settings.org_sigla, ano=ano, ultimo=0)
            db.add(seq)
        seq.ultimo += 1
        doc.numero = f"{settings.org_sigla}/{ano}/{seq.ultimo:06d}"
    doc.estado = Estado.PROTOCOLADO
    doc.protocolado_por_id, doc.protocolado_em = user.id, agora()
    auditoria.registar(db, user.username, "protocolar", f"Registado com o n.º {doc.numero}", doc.id, ip(request))
    db.commit()
    despachantes = [u.email for u in db.scalars(select(Utilizador)) if u.tem("despacho") and not u.tem("assinatura")]
    correio.enviar(despachantes + [doc.autor.email], f"[GED] {doc.numero} aguarda despacho",
                   f"O {doc.tipo.lower()} n.º {doc.numero} — «{doc.assunto}» foi protocolado por {user.nome} "
                   f"e aguarda despacho.\n\nAbrir: {settings.base_url}/documentos/{doc.id}")
    return voltar(doc.id, "protocolado")


@app.post("/documentos/{doc_id}/despachar", dependencies=[Depends(verificar_csrf)])
def despachar(doc_id: int, request: Request, despacho: str = Form(..., max_length=2000),
              signatario_id: int = Form(...), user: Utilizador = Depends(exigir("despacho")),
              db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if doc.estado != Estado.PROTOCOLADO:
        raise HTTPException(409, "O documento não aguarda despacho.")
    sig = db.get(Utilizador, signatario_id)
    if not sig or not sig.tem("assinatura"):
        raise HTTPException(400, "Signatário inválido.")
    doc.despacho_texto, doc.despachante_id, doc.despachado_em = despacho.strip(), user.id, agora()
    doc.signatario_id, doc.estado = sig.id, Estado.DESPACHADO
    auditoria.registar(db, user.username, "despachar", f"«{doc.despacho_texto}» → assinatura de {sig.nome}",
                       doc.id, ip(request))
    db.commit()
    correio.enviar([sig.email, doc.autor.email], f"[GED] {doc.numero} aguarda a sua assinatura",
                   f"Despacho de {user.nome}: «{doc.despacho_texto}»\n\n{doc.tipo} n.º {doc.numero} — "
                   f"«{doc.assunto}».\n\nAbrir: {settings.base_url}/documentos/{doc.id}")
    return voltar(doc.id, "despachado")


@app.post("/documentos/{doc_id}/devolver", dependencies=[Depends(verificar_csrf)])
def devolver(doc_id: int, request: Request, motivo: str = Form(..., max_length=2000),
             user: Utilizador = Depends(utilizador_atual), db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    pode = (doc.estado == Estado.PROTOCOLADO and user.tem("despacho")) or \
           (doc.estado == Estado.DESPACHADO and doc.signatario_id == user.id)
    if not pode:
        raise HTTPException(403, "Não pode devolver este documento.")
    doc.estado = Estado.RASCUNHO
    doc.signatario_id = None
    auditoria.registar(db, user.username, "devolver", f"Devolvido para correção: «{motivo.strip()}»", doc.id, ip(request))
    db.commit()
    correio.enviar([doc.autor.email], f"[GED] {doc.numero} devolvido para correção",
                   f"{user.nome} devolveu o documento: «{motivo.strip()}».\n\nAbrir: {settings.base_url}/documentos/{doc.id}")
    return voltar(doc.id, "devolvido")


@app.post("/documentos/{doc_id}/editar", dependencies=[Depends(verificar_csrf)])
def editar(doc_id: int, request: Request, assunto: str = Form(..., max_length=300),
           destinatario: str = Form(..., max_length=300), destinatario_email: str = Form("", max_length=200),
           corpo: str = Form(..., max_length=20000), user: Utilizador = Depends(exigir("elaboracao")),
           db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if doc.estado != Estado.RASCUNHO or doc.autor_id != user.id:
        raise HTTPException(403, "Só o autor pode editar um rascunho.")
    doc.assunto, doc.destinatario = assunto.strip(), destinatario.strip()
    doc.destinatario_email, doc.corpo = destinatario_email.strip(), texto(corpo)
    auditoria.registar(db, user.username, "editar", "Rascunho alterado", doc.id, ip(request))
    db.commit()
    return voltar(doc.id, "editado")


@app.post("/documentos/{doc_id}/assinar", dependencies=[Depends(verificar_csrf)])
def assinar(doc_id: int, request: Request, user: Utilizador = Depends(exigir("assinatura")),
            db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if doc.estado != Estado.DESPACHADO or doc.signatario_id != user.id:
        raise HTTPException(403, "Este documento não aguarda a sua assinatura.")
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codigo = "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))
    doc.codigo_verificacao = codigo
    quando = agora()
    pdf = assinar_pdf(gerar_pdf(doc, user, quando), user)
    nome = f"{doc.numero.replace('/', '-')}.pdf"
    (PDF_DIR / nome).write_bytes(pdf)
    doc.pdf_path, doc.sha256, doc.assinado_em, doc.estado = nome, sha256(pdf), quando, Estado.ASSINADO
    auditoria.registar(db, user.username, "assinar",
                       f"Assinatura PAdES · SHA-256 {doc.sha256} · código {codigo}", doc.id, ip(request))
    db.commit()
    correio.enviar([doc.autor.email], f"[GED] {doc.numero} assinado",
                   f"O {doc.tipo.lower()} n.º {doc.numero} foi assinado por {user.nome}.\n"
                   f"Verificação: {url_verificacao(codigo)}")
    if doc.destinatario_email:
        correio.enviar([doc.destinatario_email], f"{doc.tipo} n.º {doc.numero} — {doc.assunto}",
                       f"Exmo(a). Senhor(a),\n\nSegue em anexo o {doc.tipo.lower()} n.º {doc.numero}, "
                       f"assinado digitalmente por {user.nome} ({user.cargo}) em {data_extenso(quando)}.\n\n"
                       f"Autenticidade verificável em {url_verificacao(codigo)} (código {codigo}).",
                       anexo=(nome, pdf))
    return voltar(doc.id, "assinado")


@app.get("/documentos/{doc_id}/pdf")
def baixar_pdf(doc_id: int, user: Utilizador = Depends(utilizador_atual), db: Session = Depends(get_db)):
    doc = obter_doc(db, doc_id)
    if not doc.pdf_path:
        raise HTTPException(404, "Documento ainda não assinado.")
    return Response((PDF_DIR / doc.pdf_path).read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{doc.pdf_path}"'})


# ---------------------------------------------------------------- verificação pública
def _por_codigo(db: Session, codigo: str) -> Documento | None:
    codigo = codigo.strip().upper()
    return db.scalars(select(Documento).where(Documento.codigo_verificacao == codigo)).first()


@app.get("/verificar", response_class=HTMLResponse)
def verificar_form(request: Request, codigo: str | None = None):
    if codigo:
        return RedirectResponse(f"/verificar/{codigo.strip().upper()}", status_code=303)
    return templates.TemplateResponse(request, "verificar.html", ctx(request, None, doc=None, codigo=None))


@app.get("/verificar/{codigo}", response_class=HTMLResponse)
def verificar(codigo: str, request: Request, db: Session = Depends(get_db)):
    doc = _por_codigo(db, codigo)
    validacao = validar_pdf((PDF_DIR / doc.pdf_path).read_bytes()) if doc and doc.pdf_path else None
    return templates.TemplateResponse(request, "verificar.html", ctx(
        request, None, doc=doc, codigo=codigo.upper(), validacao=validacao, comparacao=None),
        status_code=200 if doc else 404)


@app.post("/verificar/{codigo}", response_class=HTMLResponse, dependencies=[Depends(verificar_csrf)])
async def verificar_ficheiro(codigo: str, request: Request, ficheiro: UploadFile = File(...),
                             db: Session = Depends(get_db)):
    doc = _por_codigo(db, codigo)
    if not doc or not doc.sha256:
        raise HTTPException(404, "Código de verificação inexistente.")
    dados = await ficheiro.read(20 * 1024 * 1024 + 1)
    if len(dados) > 20 * 1024 * 1024:
        raise HTTPException(413, "Ficheiro demasiado grande.")
    # a validação PAdES usa asyncio internamente: correr fora do event loop
    comparacao = {"identico": sha256(dados) == doc.sha256, "sha256": sha256(dados),
                  "assinatura": await run_in_threadpool(validar_pdf, dados)}
    validacao = await run_in_threadpool(validar_pdf, (PDF_DIR / doc.pdf_path).read_bytes())
    return templates.TemplateResponse(request, "verificar.html", ctx(
        request, None, doc=doc, codigo=codigo.upper(), validacao=validacao, comparacao=comparacao))


@app.get("/pki/ac-raiz.crt")
def ac_raiz():
    return Response(pki.raiz_path().read_bytes(), media_type="application/x-pem-file",
                    headers={"Content-Disposition": 'attachment; filename="ac-raiz-estado-demo.crt"'})


# ---------------------------------------------------------------- auditoria e saúde
@app.get("/auditoria", response_class=HTMLResponse)
def ver_auditoria(request: Request, user: Utilizador = Depends(exigir("admin")), db: Session = Depends(get_db)):
    from .models import Evento
    integra, total, falha = auditoria.verificar_cadeia(db)
    eventos = db.scalars(select(Evento).order_by(Evento.id.desc()).limit(200)).all()
    return templates.TemplateResponse(request, "auditoria.html", ctx(
        request, user, integra=integra, total=total, falha=falha, eventos=eventos))


@app.get("/saude")
def saude():
    return {"estado": "ok"}
