"""PKI de demonstração do Estado: AC Raiz → AC de Assinatura → certificados pessoais.

Em produção: AC Raiz offline, chaves em HSM, emissão após validação presencial,
CRL/OCSP publicados e carimbo do tempo (TSA). Aqui as chaves ficam em DATA_DIR/pki.
"""
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .config import settings

PKI_DIR = settings.data_dir / "pki"
_lock = threading.Lock()


def _nome(cn: str, ou: str | None = None) -> x509.Name:
    attrs = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "GW"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Estado da Guiné-Bissau (DEMO)"),
    ]
    if ou:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou))
    attrs.append(x509.NameAttribute(NameOID.COMMON_NAME, cn))
    return x509.Name(attrs)


def _guardar(nome: str, key, cert) -> None:
    PKI_DIR.mkdir(parents=True, exist_ok=True)
    kp = PKI_DIR / f"{nome}.key.pem"
    kp.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    kp.chmod(0o600)
    (PKI_DIR / f"{nome}.crt.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _carregar(nome: str):
    key = serialization.load_pem_private_key((PKI_DIR / f"{nome}.key.pem").read_bytes(), None)
    cert = x509.load_pem_x509_certificate((PKI_DIR / f"{nome}.crt.pem").read_bytes())
    return key, cert


def _emitir(subject, issuer_name, issuer_key, pub, dias, ca: bool, pathlen=None, utilizador=False):
    agora = datetime.now(timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(pub)
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(minutes=5))
        .not_valid_after(agora + timedelta(days=dias))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=pathlen), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
    )
    if ca:
        b = b.add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
    else:
        b = b.add_extension(
            x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
    if issuer_key is not None:
        b = b.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        )
    return b


def garantir_acs() -> None:
    with _lock:
        if (PKI_DIR / "ac-assinatura.crt.pem").exists():
            return
        raiz_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        raiz_nome = _nome("AC Raiz do Estado da Guiné-Bissau - DEMO")
        raiz = _emitir(raiz_nome, raiz_nome, raiz_key, raiz_key.public_key(), 3650 * 2, True, 1).sign(
            raiz_key, hashes.SHA256()
        )
        _guardar("ac-raiz", raiz_key, raiz)

        sub_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        sub_nome = _nome("AC de Assinatura Digital do Estado - DEMO")
        sub = _emitir(sub_nome, raiz_nome, raiz_key, sub_key.public_key(), 3650, True, 0).sign(
            raiz_key, hashes.SHA256()
        )
        _guardar("ac-assinatura", sub_key, sub)


def certificado_utilizador(username: str, nome: str, email: str, unidade: str) -> tuple[Path, Path]:
    """Garante (e se preciso emite) o certificado de assinatura do utilizador."""
    garantir_acs()
    alvo = f"user-{username}"
    with _lock:
        if not (PKI_DIR / f"{alvo}.crt.pem").exists():
            sub_key, sub = _carregar("ac-assinatura")
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name(
                list(_nome(nome, unidade)) + [x509.NameAttribute(NameOID.EMAIL_ADDRESS, email)]
            )
            cert = (
                _emitir(subject, sub.subject, sub_key, key.public_key(), 730, False)
                .add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False)
                .sign(sub_key, hashes.SHA256())
            )
            _guardar(alvo, key, cert)
    return PKI_DIR / f"{alvo}.key.pem", PKI_DIR / f"{alvo}.crt.pem"


def cadeia() -> list[Path]:
    garantir_acs()
    return [PKI_DIR / "ac-assinatura.crt.pem", PKI_DIR / "ac-raiz.crt.pem"]


def raiz_path() -> Path:
    garantir_acs()
    return PKI_DIR / "ac-raiz.crt.pem"
