"""Diretório de demonstração.

Espelha os utilizadores do realm Keycloak (infra/keycloak/realm-estado.json).
Em produção, a fonte é o diretório único do Estado (LDAP) sincronizado pelo SSO.
"""

DOMINIO = "demo.gov.gw"

UTILIZADORES = [
    {
        "username": "ana.mendes",
        "nome": "Ana Mendes",
        "cargo": "Técnica de Protocolo",
        "unidade": "Secretaria-Geral",
        "roles": ["protocolo"],
    },
    {
        "username": "carla.vieira",
        "nome": "Carla Vieira",
        "cargo": "Técnica Superior",
        "unidade": "Direção de Serviços Jurídicos",
        "roles": ["elaboracao"],
    },
    {
        "username": "bruno.sa",
        "nome": "Bruno Sá",
        "cargo": "Diretor-Geral de Administração",
        "unidade": "Direção-Geral de Administração",
        "roles": ["despacho"],
    },
    {
        "username": "domingos.co",
        "nome": "Domingos Có",
        "cargo": "Ministro",
        "unidade": "Gabinete do Ministro",
        "roles": ["despacho", "assinatura"],
    },
    {
        "username": "eva.admin",
        "nome": "Eva Cabral",
        "cargo": "Administradora de Sistemas",
        "unidade": "Direção de Tecnologias de Informação",
        "roles": ["admin"],
    },
]

for _u in UTILIZADORES:
    _u["email"] = f"{_u['username']}@{DOMINIO}"

# Caixa funcional que recebe os ofícios assinados (simula outra instituição)
CAIXA_EXTERNA = f"gabinete.financas@{DOMINIO}"
