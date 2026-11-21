"""Teste ponta a ponta do fluxo: ofício → protocolo → despacho → assinatura → verificação."""
import os
import re
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ged-test-")
os.environ["AUTH_MODE"] = "local"
os.environ["SMTP_HOST"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def cli():
    with TestClient(app) as c:
        yield c


def entrar(cli, username):
    cli.cookies.clear()
    html = cli.get("/login").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    r = cli.post("/login/local", data={"csrf": csrf, "username": username}, follow_redirects=False)
    assert r.status_code == 303
    # o token CSRF é renovado no login
    return re.search(r'<meta name="csrf" content="([^"]+)"', cli.get("/").text).group(1)


def post(cli, url, csrf, **data):
    return cli.post(url, data={"csrf": csrf, **data}, follow_redirects=False)


def test_fluxo_completo(cli):
    # 1. elaboração
    csrf = entrar(cli, "carla.vieira")
    r = post(cli, "/documentos", csrf, assunto="Pedido de dados orçamentais", destinatario="Ministro das Finanças",
             destinatario_email="gabinete.financas@demo.gov.gw", corpo="Excelência,\r\n\r\nSolicito os dados.")
    doc_url = r.headers["location"].split("?")[0]
    doc_id = doc_url.rsplit("/", 1)[1]
    assert cli.get(doc_url).text.count("<p>Excelência,</p>") == 1  # parágrafos preservados
    # o protocolo não pode registar antes da submissão
    assert post(cli, f"/documentos/{doc_id}/submeter", csrf).status_code == 303

    # 2. protocolo
    csrf = entrar(cli, "ana.mendes")
    assert post(cli, f"/documentos/{doc_id}/protocolar", csrf).status_code == 303
    assert re.search(r"DEMO/\d{4}/000001", cli.get(doc_url).text)

    # perfil errado não despacha
    assert post(cli, f"/documentos/{doc_id}/despachar", csrf, despacho="x", signatario_id="4").status_code == 403

    # 3. despacho
    csrf = entrar(cli, "bruno.sa")
    page = cli.get(doc_url).text
    sig_id = re.search(r'<option value="(\d+)">Domingos', page).group(1)
    assert post(cli, f"/documentos/{doc_id}/despachar", csrf, despacho="Concordo.", signatario_id=sig_id).status_code == 303

    # 4. assinatura (só o signatário designado)
    csrf = entrar(cli, "domingos.co")
    assert post(cli, f"/documentos/{doc_id}/assinar", csrf).status_code == 303
    page = cli.get(doc_url).text
    codigo = re.search(r"<code>([A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4})</code>", page).group(1)
    pdf = cli.get(f"{doc_url}/pdf").content
    assert pdf.startswith(b"%PDF")

    # 5. verificação pública (sem sessão)
    cli.cookies.clear()
    v = cli.get(f"/verificar/{codigo}")
    assert v.status_code == 200 and "Documento autêntico" in v.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', v.text).group(1)
    ok = cli.post(f"/verificar/{codigo}", data={"csrf": csrf}, files={"ficheiro": ("o.pdf", pdf, "application/pdf")})
    assert "idêntico ao original" in ok.text
    assert "Documento autêntico" in ok.text  # validação também funciona no endpoint assíncrono

    adulterado = pdf.replace(b"Solicito", b"Exijo!!!", 1) if b"Solicito" in pdf else pdf[:-200] + b"0" * 200
    mau = cli.post(f"/verificar/{codigo}", data={"csrf": csrf}, files={"ficheiro": ("x.pdf", adulterado, "application/pdf")})
    assert "diferente do original" in mau.text

    assert cli.get("/verificar/AAAA-BBBB-CCCC").status_code == 404

    # auditoria íntegra
    entrar(cli, "eva.admin")
    assert "Cadeia íntegra" in cli.get("/auditoria").text


def test_csrf_obrigatorio(cli):
    entrar(cli, "carla.vieira")
    r = cli.post("/documentos", data={"csrf": "errado", "assunto": "a", "destinatario": "b", "corpo": "c"})
    assert r.status_code == 403


def test_auditoria_detecta_adulteracao(cli):
    from app.db import SessionLocal
    from app.models import Evento
    from app import auditoria
    with SessionLocal() as db:
        ev = db.get(Evento, 2)
        original = ev.detalhe
        ev.detalhe = "adulterado"
        db.commit()
        assert auditoria.verificar_cadeia(db)[0] is False
        ev.detalhe = original
        db.commit()
        assert auditoria.verificar_cadeia(db)[0] is True
