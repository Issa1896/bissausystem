"""Geração do ofício em PDF (com QR de verificação) e assinatura PAdES."""
import hashlib
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from pyhanko.keys import load_cert_from_pemder
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from . import pki
from .config import settings

TZ = ZoneInfo("Africa/Bissau")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def data_extenso(dt: datetime) -> str:
    dt = dt.astimezone(TZ)
    return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}"


def url_verificacao(codigo: str) -> str:
    return f"{settings.base_url}/verificar/{codigo}"


def gerar_pdf(doc, signatario, assinado_em: datetime) -> bytes:
    buf = BytesIO()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontName="Helvetica", fontSize=11, leading=16)
    corpo = ParagraphStyle("c", parent=normal, alignment=TA_JUSTIFY, firstLineIndent=12 * mm, spaceAfter=8)
    centro = ParagraphStyle("ce", parent=normal, alignment=TA_CENTER)
    cab1 = ParagraphStyle("h1", parent=centro, fontName="Helvetica-Bold", fontSize=12, leading=16)
    cab2 = ParagraphStyle("h2", parent=centro, fontSize=10, leading=14, textColor=colors.HexColor("#444444"))

    url = url_verificacao(doc.codigo_verificacao)

    def moldura(canvas, _doc):
        w, h = A4
        canvas.saveState()
        # faixa com as cores nacionais
        for i, cor in enumerate(["#CE1126", "#FCD116", "#009E49"]):
            canvas.setFillColor(colors.HexColor(cor))
            canvas.rect(0, h - 6 * mm + i * 2 * mm, w, 2 * mm, stroke=0, fill=1)
        # marca d'água de demonstração
        canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.07))
        canvas.setFont("Helvetica-Bold", 70)
        canvas.translate(w / 2, h / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "DEMONSTRAÇÃO")
        canvas.restoreState()

        # rodapé com QR
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
        canvas.line(20 * mm, 38 * mm, w - 20 * mm, 38 * mm)
        qr = QrCodeWidget(url)
        b = qr.getBounds()
        tam = 30 * mm
        d = Drawing(tam, tam, transform=[tam / (b[2] - b[0]), 0, 0, tam / (b[3] - b[1]), 0, 0])
        d.add(qr)
        renderPDF.draw(d, canvas, 20 * mm, 6 * mm)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(colors.black)
        x = 54 * mm
        canvas.drawString(x, 30 * mm, f"Documento assinado digitalmente por {signatario.nome} ({signatario.cargo})")
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(x, 25 * mm, f"em {assinado_em.astimezone(TZ):%d/%m/%Y às %H:%M} (hora de Bissau) · assinatura PAdES")
        canvas.drawString(x, 20 * mm, f"Verifique a autenticidade em {settings.base_url}/verificar")
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(x, 14 * mm, f"Código de verificação: {doc.codigo_verificacao}")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(x, 9 * mm, f"{doc.tipo} n.º {doc.numero} · página {canvas.getPageNumber()}")
        canvas.restoreState()

    story = [
        Paragraph(escape(settings.org_pais), cab1),
        Paragraph(escape(settings.org_nome), cab2),
        Paragraph(escape(doc.autor.unidade), cab2),
        Spacer(1, 10 * mm),
        Paragraph(f"<b>{escape(doc.tipo)} n.º {escape(doc.numero)}</b>", normal),
        Paragraph(f"{escape(settings.org_local)}, {data_extenso(assinado_em)}", normal),
        Spacer(1, 6 * mm),
        Paragraph(f"<b>A:</b> {escape(doc.destinatario)}", normal),
        Paragraph(f"<b>Assunto:</b> {escape(doc.assunto)}", normal),
        Spacer(1, 6 * mm),
    ]
    for par in [p.strip() for p in doc.corpo.replace("\r", "").split("\n\n") if p.strip()]:
        story.append(Paragraph(escape(par).replace("\n", "<br/>"), corpo))
    story += [
        Spacer(1, 10 * mm),
        Paragraph("Com os melhores cumprimentos,", normal),
        Spacer(1, 8 * mm),
        Paragraph(f"<b>{escape(signatario.nome)}</b>", centro),
        Paragraph(escape(signatario.cargo), centro),
    ]
    if doc.despacho_texto:
        story += [
            Spacer(1, 8 * mm),
            Paragraph(
                f"<font size=8 color='#555555'>Despacho de {escape(doc.despachante.nome)} "
                f"({doc.despachado_em.astimezone(TZ):%d/%m/%Y}): {escape(doc.despacho_texto)}</font>",
                normal,
            ),
        ]

    SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=25 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=45 * mm,
        title=f"{doc.tipo} {doc.numero}", author=signatario.nome, subject=doc.assunto,
        creator=f"GED do Estado — {settings.org_nome}",
    ).build(story, onFirstPage=moldura, onLaterPages=moldura)
    return buf.getvalue()


def assinar_pdf(pdf: bytes, signatario) -> bytes:
    key_path, cert_path = pki.certificado_utilizador(
        signatario.username, signatario.nome, signatario.email, signatario.unidade
    )
    signer = signers.SimpleSigner.load(
        str(key_path), str(cert_path), ca_chain_files=tuple(str(p) for p in pki.cadeia())
    )
    meta = signers.PdfSignatureMetadata(
        field_name="AssinaturaGED",
        reason="Assinatura de documento oficial",
        location=settings.org_local,
        subfilter=fields.SigSeedSubFilter.PADES,
        md_algorithm="sha256",
    )
    out = signers.sign_pdf(IncrementalPdfFileWriter(BytesIO(pdf)), meta, signer=signer)
    return out.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validar_pdf(data: bytes) -> dict:
    """Valida criptograficamente a(s) assinatura(s) do PDF contra a AC Raiz do Estado."""
    res = {"assinaturas": [], "valido": False, "erro": None}
    try:
        raiz = load_cert_from_pemder(str(pki.raiz_path()))
        vc = ValidationContext(trust_roots=[raiz], allow_fetching=False, revocation_mode="soft-fail")
        reader = PdfFileReader(BytesIO(data))
        sigs = reader.embedded_signatures
        if not sigs:
            res["erro"] = "O ficheiro não contém assinaturas digitais."
            return res
        for sig in sigs:
            st = validate_pdf_signature(sig, vc)
            res["assinaturas"].append({
                "signatario": st.signing_cert.subject.native.get("common_name"),
                "integro": bool(st.intact and st.valid),
                "confiavel": bool(st.trusted),
                "cobertura_total": st.coverage.name == "ENTIRE_FILE",
                "data": st.signer_reported_dt,
            })
        res["valido"] = all(a["integro"] and a["confiavel"] and a["cobertura_total"] for a in res["assinaturas"])
    except Exception as exc:  # ficheiro corrompido / não-PDF
        res["erro"] = f"Não foi possível validar o ficheiro: {type(exc).__name__}"
    return res
