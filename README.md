# Bissau System — E-mail Institucional + Gestão Documental do Estado (demonstração)

Prova de conceito funcional que acompanha a proposta ao concurso **WARDIP-F-002-2026**
(ver o plano completo em [`docs/PLANO.md`](docs/PLANO.md)).

Demonstra, ponta a ponta e com componentes reais:

```
Login Único (Keycloak) ──► GED: ofício → protocolo → despacho → assinatura PAdES → verificação por QR
        │                          │ notificações e envio do ofício assinado (SMTP)
        └──► Webmail (Roundcube) ◄─┴── Servidor de correio (Postfix + Dovecot + Rspamd)
             entrada por SSO: o token OIDC autentica o IMAP (XOAUTH2), sem senha de e-mail
```

| Serviço | Endereço | Função |
|---|---|---|
| GED do Estado | http://localhost:8000 | Expediente eletrónico (FastAPI + PostgreSQL) |
| Login Único | http://localhost:8080 | Keycloak: SSO OIDC, MFA TOTP, perfis, política de senhas, anti força-bruta |
| Webmail | http://localhost:8081 | Roundcube com botão «Login Único do Estado» |
| Correio | `mailserver` (25/143/587 em 127.0.0.1) | docker-mailserver com autenticação OAuth2 |

## Arrancar

Requisitos: Docker com Compose v2 (≈ 3 GB de RAM livres).

```bash
docker compose up -d --build
```

Após ~1 minuto, abrir http://localhost:8000 e **Entrar**. Senha de todos os utilizadores de demonstração: `Demo#2026`.

| Utilizador | Cargo | Perfil no fluxo |
|---|---|---|
| `carla.vieira` | Técnica Superior | elabora e submete o ofício |
| `ana.mendes` | Técnica de Protocolo | regista no protocolo (número único `DEMO/2026/000001`) |
| `bruno.sa` | Diretor-Geral | despacha e encaminha para assinatura |
| `domingos.co` | Ministro | assina digitalmente |
| `eva.admin` | Administradora de Sistemas | consulta a trilha de auditoria |
| `gabinete.financas@demo.gov.gw` | caixa funcional (só webmail) | recebe o ofício assinado em anexo |

Consola de administração do Keycloak: http://localhost:8080/admin (`admin` / `Admin#Demo2026`).

## Roteiro de demonstração (≈ 5 minutos)

1. **carla.vieira** → *Novo ofício* → *Guardar rascunho* → *Submeter ao protocolo*. Sair.
2. **ana.mendes** → o ofício está na caixa de tarefas → *Registar no protocolo*. Sair.
3. **bruno.sa** → *Despachar* (escolhe o Ministro como signatário). Sair.
4. **domingos.co** → *Assinar digitalmente* → *Abrir PDF assinado* (QR no rodapé).
5. Ler o QR com o telemóvel (ou abrir *Página de verificação*) → **Documento autêntico**. Carregar o PDF para confirmar que é idêntico; um PDF alterado é rejeitado.
6. Abrir http://localhost:8081 → **Login Único do Estado** → a caixa da Carla tem as notificações de cada etapa.
7. No webmail, entrar como `gabinete.financas@demo.gov.gw` → o ofício chegou com o PDF assinado em anexo.
8. **eva.admin** → *Auditoria* → cadeia de eventos íntegra (encadeada por SHA-256).

Capturas de ecrã em [`docs/capturas/`](docs/capturas) e um PDF de exemplo em
[`docs/exemplo-oficio-assinado.pdf`](docs/exemplo-oficio-assinado.pdf).

## Segurança implementada na demo

- **SSO OIDC** com PKCE (GED) e *client secret*; logout único (termina a sessão no Keycloak).
- **MFA TOTP** disponível no realm; política de senhas forte; bloqueio progressivo após 5 falhas; eventos de login auditados.
- **Autorização por perfil** (protocolo, elaboração, despacho, assinatura, admin) verificada no servidor em cada ação; só o signatário designado pode assinar.
- **Assinatura PAdES** (SHA-256) com PKI própria: AC Raiz → AC de Assinatura → certificado pessoal (validação independente: `pdfsig docs/exemplo-oficio-assinado.pdf`).
- **Verificação pública** por código/QR: compara o SHA-256 do ficheiro e valida criptograficamente a assinatura e a cadeia de certificação.
- **Trilha de auditoria imutável** (cada evento encadeado ao anterior por hash; adulterações detetadas).
- Proteção **CSRF**, cookies de sessão assinados (`HttpOnly`, `SameSite=Lax`, `Secure` opcional), cabeçalhos CSP/X-Frame-Options/nosniff, limites de tamanho de upload, contentor sem root.
- Correio: Rspamd (antispam), proteção contra falsificação de remetente, autenticação IMAP/SMTP por token OAuth2.

## O que muda em produção

| Demo | Produção (ver `docs/PLANO.md` §5) |
|---|---|
| HTTP em `localhost` | TLS 1.3 em todos os serviços, HSTS, `COOKIE_SECURE=true`, IMAPS/SMTPS apenas |
| Senhas e segredos fixos (`*-TROCAR`) | Segredos gerados e guardados em cofre (Vault); `.env` fora do repositório |
| Chaves da PKI em disco | AC Raiz offline, chaves em HSM, CRL/OCSP, carimbo do tempo (TSA) |
| Sem DKIM/DMARC/antivírus | DKIM + SPF + DMARC `p=reject`, MTA-STS, ClamAV |
| Um único nó | Alta disponibilidade, site de DR, backup imutável, monitorização e SIEM |
| Utilizadores definidos em ficheiro | Diretório LDAP único do Estado federado no Keycloak |

## Desenvolvimento

```bash
cd ged && pip install -r requirements.txt pytest
python -m pytest -q tests            # fluxo completo em modo local (sem Docker)
AUTH_MODE=local uvicorn app.main:app --reload   # GED isolado, com login de teste
```

Teste com navegador real sobre o `docker compose` em execução (Playwright):

```bash
node tests-e2e/fluxo-sso.cjs
```

Para alterar utilizadores ou domínio, editar `ged/app/diretorio.py` e regenerar a configuração do Keycloak e das caixas de correio:

```bash
python3 scripts/gerar_config.py
```

## Estrutura

```
docker-compose.yml          serviços da demo
ged/                        aplicação de gestão documental (FastAPI)
  app/main.py               rotas e fluxo (estados, perfis, notificações)
  app/documentos_pdf.py     PDF oficial, QR, assinatura e validação PAdES
  app/pki.py                PKI de demonstração do Estado
  app/auditoria.py          trilha de auditoria encadeada por hash
  tests/                    testes do fluxo
infra/keycloak/             realm «estado» (gerado por scripts/gerar_config.py)
infra/mailserver/config/    caixas de correio e ajustes do Dovecot
infra/roundcube/sso.php     webmail com Login Único
tests-e2e/                  teste ponta a ponta com navegador
docs/                       plano do concurso, capturas, PDF de exemplo
```
