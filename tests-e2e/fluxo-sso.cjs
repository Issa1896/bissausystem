// Teste ponta a ponta com navegador real (Playwright) sobre o docker-compose em execução.
// Uso: node tests-e2e/fluxo-sso.cjs   (CAPTURAS=docs/capturas para guardar ecrãs)
const { chromium } = require('playwright');
const GED = process.env.GED_URL || 'http://localhost:8000';
const WEBMAIL = process.env.WEBMAIL_URL || 'http://localhost:8081';
const SENHA = process.env.SENHA_DEMO || 'Demo#2026';
const CAP = process.env.CAPTURAS;

let browser;
async function sessao(username) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: CAP ? 2 : 1, locale: 'pt-PT' });
  const page = await ctx.newPage();
  await page.goto(`${GED}/login`);
  await page.waitForURL(/localhost:8080\/realms\/estado/);           // ecrã do Login Único
  await page.fill('#username', username);
  await page.fill('#password', SENHA);
  await page.click('#kc-login');
  await page.waitForURL(`${GED}/`);
  return { ctx, page };
}
async function cap(page, nome) { if (CAP) await page.screenshot({ path: `${CAP}/${nome}.png`, fullPage: true }); }
function ok(cond, msg) { if (!cond) throw new Error('FALHOU: ' + msg); console.log('✔', msg); }

(async () => {
  browser = await chromium.launch();
  const assunto = `Pedido de mapas de execução orçamental ${Date.now() % 100000}`;

  // 0. ecrã de login único
  { const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: CAP ? 2 : 1 });
    const p = await ctx.newPage(); await p.goto(`${GED}/login`); await p.waitForSelector('#username'); await cap(p, '01-login-unico'); await ctx.close(); }

  // 1. elaboração
  let { ctx, page } = await sessao('carla.vieira');
  await page.click('text=Novo ofício');
  await page.fill('input[name=assunto]', assunto);
  await page.fill('input[name=destinatario]', 'Sua Excelência o Ministro das Finanças');
  await page.fill('textarea[name=corpo]', 'Excelência,\n\nNo âmbito do acompanhamento da execução do Orçamento Geral do Estado, solicito a Vossa Excelência os mapas de execução orçamental do 3.º trimestre de 2026.\n\nApresento a Vossa Excelência os protestos da mais elevada consideração.');
  await cap(page, '02-elaboracao');
  await page.click('button:has-text("Guardar rascunho")');
  const docUrl = page.url().split('?')[0];
  await page.click('button:has-text("Submeter ao protocolo")');
  ok((await page.textContent('.cab-doc')).includes('aguarda protocolo'), 'ofício elaborado e submetido');
  await ctx.close();

  // 2. protocolo
  ({ ctx, page } = await sessao('ana.mendes'));
  ok((await page.textContent('main')).includes(assunto), 'aparece na caixa de tarefas do protocolo');
  await page.goto(docUrl);
  await page.click('button:has-text("Registar no protocolo")');
  const numero = (await page.textContent('.cab-doc .sub')).match(/DEMO\/\d{4}\/\d{6}/)[0];
  ok(numero, `protocolado com o n.º ${numero}`);
  await ctx.close();

  // 3. despacho
  ({ ctx, page } = await sessao('bruno.sa'));
  await page.goto(docUrl);
  await cap(page, '03-despacho');
  await page.click('button:has-text("Despachar")');
  ok((await page.textContent('.cab-doc')).includes('aguarda assinatura'), 'despachado para o Ministro');
  await ctx.close();

  // 4. assinatura
  ({ ctx, page } = await sessao('domingos.co'));
  await page.goto(docUrl);
  await page.click('button:has-text("Assinar digitalmente")');
  const codigo = (await page.textContent('.meta code')).trim();
  ok(/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(codigo), `assinado (PAdES), código ${codigo}`);
  await cap(page, '04-assinado');
  const pdf = await (await ctx.request.get(`${docUrl}/pdf`)).body();
  require('fs').writeFileSync('/tmp/oficio-assinado.pdf', pdf);
  ok(pdf.subarray(0, 4).toString() === '%PDF', 'PDF assinado descarregado');
  await ctx.close();

  // 5. verificação pública (sem login) + comparação do ficheiro
  { const c = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: CAP ? 2 : 1 });
    const p = await c.newPage();
    await p.goto(`${GED}/verificar/${codigo}`);
    ok((await p.textContent('main')).includes('Documento autêntico'), 'verificação pública: autêntico');
    await p.setInputFiles('input[type=file]', '/tmp/oficio-assinado.pdf');
    await p.click('button:has-text("Comparar")');
    const apos = await p.textContent('main');
    ok(apos.includes('idêntico ao original') && apos.includes('Documento autêntico'), 'cópia carregada é idêntica ao original e assinatura válida');
    await cap(p, '05-verificacao');
    await c.close(); }

  // 6. webmail com Login Único (OAuth2 → IMAP XOAUTH2)
  { const c = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: CAP ? 2 : 1 });
    const p = await c.newPage();
    await p.goto(WEBMAIL);
    await p.click('text=Login Único do Estado');
    await p.waitForURL(/localhost:8080\/realms\/estado/);
    await p.fill('#username', 'carla.vieira'); await p.fill('#password', SENHA); await p.click('#kc-login');
    await p.waitForURL(new RegExp(`${WEBMAIL}/\\?_task=mail`), { timeout: 30000 });
    await p.waitForSelector('#messagelist', { timeout: 30000 });
    let txt = '';
    for (let i = 0; i < 10 && !txt.includes(`${numero} assinado`); i++) {
      await p.waitForTimeout(2000); await p.reload(); await p.waitForSelector('#messagelist'); txt = await p.textContent('#messagelist');
    }
    ok(txt.includes(`${numero} assinado`), 'autora recebeu a notificação no webmail (entrada por SSO)');
    await cap(p, '06-webmail-sso');
    await c.close(); }

  // 7. caixa funcional do destinatário recebe o ofício com PDF anexo
  { const c = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: CAP ? 2 : 1 });
    const p = await c.newPage();
    await p.goto(WEBMAIL);
    await p.fill('#rcmloginuser', 'gabinete.financas@demo.gov.gw'); await p.fill('#rcmloginpwd', SENHA);
    await p.click('#rcmloginsubmit');
    await p.waitForSelector('#messagelist');
    const linha = p.locator('#messagelist tr', { hasText: numero }).first();
    await linha.waitFor({ timeout: 20000 });
    await linha.dblclick();
    await p.waitForTimeout(2500);
    const corpo = await p.frameLocator('#messagecontframe').locator('body').textContent().catch(async () => await p.textContent('body'));
    ok(corpo.includes(codigo) && corpo.includes('.pdf'), 'destinatário recebeu o ofício com o PDF assinado em anexo');
    await cap(p, '07-destinatario');
    await c.close(); }

  await browser.close();
  console.log('\nFluxo completo validado.');
})().catch(async e => { console.error(e); if (browser) await browser.close(); process.exit(1); });
