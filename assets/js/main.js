console.log("UrnaWeb Main JS Ativo!");

/* ==========================================================================
   VARIÁVEIS DE ESTADO E INICIALIZAÇÃO
   ========================================================================== */
window._data = [];
window._temp = null;
window._sel = [];
window._idx = 0;
window._title = '';
window._fotoTemp = '';
window._maxVotos = 1;
window._idioma = 'pt';
window._totalEleitores = 0;

// Bloqueio de inspeção básica
document.addEventListener('contextmenu', e => e.preventDefault());
document.onkeydown = function(e) { 
    if (e.keyCode == 123 || (e.ctrlKey && e.shiftKey && (e.keyCode == 73 || e.keyCode == 74)) || (e.ctrlKey && e.keyCode == 85)) return false; 
};

/* ==========================================================================
   NAVEGAÇÃO
   ========================================================================== */
window.GO = (id) => {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if(target) target.classList.add('active');
    if(window.TR) window.TR(window._idioma);
};

/* ==========================================================================
   AUTENTICAÇÃO E SEGURANÇA
   ========================================================================== */
window.V = async function() { 
    let e = document.getElementById('uE').value.trim().toLowerCase(); 
    if(!e.endsWith('@gmail.com')) return alert("Use um e-mail @gmail.com válido!"); 
    
    localStorage.setItem('urna_user_email', e); 
    let btn = document.getElementById('L2'); 
    btn.disabled = true; btn.innerText = "Processando..."; 

    try { 
        let r = await fetch(window._cfg.u + '/?email=' + encodeURIComponent(e)); 
        let d = await r.json(); 
        if(d.pay_required === true) { window.GO('pay'); return; } 

        let cod = (d.codigo || d.code || d).toString().trim();
        localStorage.setItem('urna_vault', cod); 

        await emailjs.send(window._cfg.s, window._cfg.t, { to_email: e, validation_code: cod });
        alert("TOKEN ENVIADO PARA: " + e); 
        window.GO('verify'); 
    } catch(err) { 
        alert("Falha ao conectar. Verifique sua conexão."); 
    } finally { 
        btn.disabled = false;
    } 
};

window.C = () => { 
    let d = document.getElementById('iC').value.trim();
    if(d === (localStorage.getItem('urna_vault') || "").trim()) window.GO('setup'); 
    else alert("Token Incorreto!"); 
};

window.RESET_TOTAL_E_LOGOUT = () => {
    if(confirm("Deseja encerrar e sair? Uma nova eleição exigirá novo login e o limite de 10 votos voltará a valer.")) {
        
        // 1. Limpa os dados da eleição (votos e candidatos)
        window._data = [];
        window._temp = null;
        window._totalEleitores = 0;
        
        // 2. DESTROI O CRÉDITO DO CUPOM: Garante que a próxima eleição comece travada
        localStorage.removeItem('urna_creditos'); 
        
        // 3. REMOVE O LOGIN E TOKEN: Força a volta para a tela de E-mail/Gmail
        localStorage.removeItem('urna_user_email');
        localStorage.removeItem('urna_vault');
        
        // 4. Limpa o visor visual de votos
        const visor = document.getElementById('voterCountDisplay');
        if(visor) visor.innerText = "0";

        // 5. DIRECIONA PARA O GMAIL (Tela de Login)
        alert("Sessão encerrada com sucesso.");
        window.GO('login'); 
    }
};

/* ==========================================================================
   CONFIGURAÇÃO DA ELEIÇÃO
   ========================================================================== */
window.N = () => { 
    window._title = document.getElementById('tE').value; 
    window._maxVotos = parseInt(document.getElementById('maxV').value) || 1; 
    window.GO('setupCargo'); 
};

window.PREV = (f) => { 
    if (f.files && f.files[0]) { 
        let r = new FileReader(); 
        r.onload = (e) => { 
            window._fotoTemp = e.target.result; 
            document.getElementById('imgPrev').src = e.target.result; 
            document.getElementById('imgPrev').style.display = 'block'; 
        }; 
        r.readAsDataURL(f.files[0]); 
    } 
};

window.A = () => {
    const cargo = document.getElementById('nC').value.trim();
    const nome = document.getElementById('nCand').value.trim();
    if (!cargo || !nome) return alert("Preencha cargo e nome!");
    if (!window._temp) window._temp = { n: cargo, c: [], branco: 0 };
    window._temp.c.push({ n: nome, v: 0, f: window._fotoTemp });
    document.getElementById('listaTemporaria').innerHTML += `<div style="padding:5px;border-bottom:1px solid rgba(255,255,255,0.1)">👤 <b>${nome}</b></div>`;
    document.getElementById('nCand').value = ''; window._fotoTemp = '';
    document.getElementById('imgPrev').style.display = 'none';
};

window.SAVE = () => {
    if (!window._temp) return alert("Adicione candidatos primeiro!");
    window._data.push(JSON.parse(JSON.stringify(window._temp))); 
    window._temp = null;
    document.getElementById('nC').value = '';
    document.getElementById('listaTemporaria').innerHTML = '';
    alert("Cargo salvo!");
};

window.START_VOTE_PROCESS = () => {
    if (window._temp) { window._data.push(JSON.parse(JSON.stringify(window._temp))); window._temp = null; }
    if (window._data.length === 0) return alert("Adicione candidatos primeiro!");
    window._idx = 0;
    window._totalEleitores = 0;
    window.RUN();
    window.GO('urna');
};

/* ==========================================================================
   URNA (VOTAÇÃO) - CORRIGIDA
   ========================================================================== */
window.RUN = () => {
    const displayCargo = document.getElementById('uT');
    const grid = document.getElementById('gridUrna');
    const cargoAtual = window._data[window._idx];
    displayCargo.innerText = cargoAtual.n.toUpperCase();
    grid.innerHTML = ''; window._sel = [];

    cargoAtual.c.forEach((can, i) => {
        const card = document.createElement('div');
        card.className = 'cand-card';
        card.style.cssText = `background:white;color:black;padding:15px;border-radius:12px;text-align:center;cursor:pointer;border:4px solid transparent;`;
        const img = can.f ? `<img src="${can.f}" style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:8px;margin-bottom:10px;">` : `<div style="width:100%;height:100px;background:#eee;border-radius:8px;display:flex;align-items:center;justify-content:center;margin-bottom:10px;"><i class="fas fa-user fa-2x"></i></div>`;
        card.innerHTML = `${img}<b>${can.n}</b>`;
        card.onclick = () => {
            if (window._sel.includes(i)) {
                window._sel = window._sel.filter(item => item !== i);
                card.style.borderColor = "transparent";
            } else if (window._sel.length < window._maxVotos) {
                window._sel.push(i);
                card.style.borderColor = "var(--success)";
            }
        };
        grid.appendChild(card);
    });
};

window.VOTE = () => { 
    if(!window._sel.length) return alert("Selecione um candidato!"); 
    window._sel.forEach(i => window._data[window._idx].c[i].v++); 
    window.PROXIMO_PASSO();
};

window.BRANCO = () => {
    window._data[window._idx].branco++; // Salva no objeto da eleição atual
    window.PROXIMO_PASSO();
};

window.PROXIMO_PASSO = () => {
    window.BIP();
    window._idx++; 

    if(window._idx < window._data.length) { 
        window.RUN(); 
    } else { 
        window._totalEleitores++;
        if(document.getElementById('voterCountDisplay')) {
            document.getElementById('voterCountDisplay').innerText = window._totalEleitores;
        }

        // ==================== TRAVA ATUALIZADA PIX / DOIS PLANOS ====================
        let credito = localStorage.getItem('urna_creditos');
        let temAcesso = (credito === "ILIMITADO" || credito === "USO_UNICO_ATIVO" || window.eleicaoDesbloqueada === true);

        // Se bateu 10 ou mais eleitores e NÃO tem acesso liberado, bloqueia na hora!
        if (window._totalEleitores >= 10 && !temAcesso) {
            // Renderiza o PIX e o PayPal dinamicamente através do script
            window.MOUNT_PAYMENT();
            // Direciona para a tela de pagamentos
            window.GO('pay'); 
            return; 
        }
        // ============================================================================

        // Se passou da trava (tem acesso pago ou ainda está abaixo de 10 eleitores), continua
        alert("Voto Confirmado!"); 
        window._idx = 0; 
        window.RUN();
    }
};

/* ==========================================================================
   RESULTADOS E SUGESTÕES - CORRIGIDO
   ========================================================================== */
window.CONFIRM_END = () => { 
    if(prompt("Senha para encerrar (1357):") === "1357") {
        window.MOUNT_RESULT(false); 
        window.GO('res');
    } else alert("Senha incorreta!");
};

/* ==========================================================================
   SOLUÇÃO DEFINITIVA PARA PDF (APURAÇÃO URNAWEB)
   ========================================================================== */
window.MOUNT_RESULT = (fotos) => {
    const out = document.getElementById('pC');
    
    // Usamos largura de 700px dentro de uma área de 750px (50px de sobra de segurança)
    let html = `
    <div id="pdf-content-wrapper" style="font-family: Arial, sans-serif; color: #000; background: #fff; padding: 30px; width: 700px; margin: 0; box-sizing: border-box; text-align: left;">
        
        <div style="text-align: center; border-bottom: 4px solid #0a2a66; padding-bottom: 15px; margin-bottom: 25px;">
            <h1 style="margin: 0; font-size: 26px; color: #0a2a66; letter-spacing: 1px;">${window._title.toUpperCase()}</h1>
            <p style="margin: 5px 0; font-size: 13px; color: #444;">Relatório Oficial de Apuração Presbiteriana</p>
            <p style="margin: 5px 0; font-size: 11px; color: #888;">Gerado em: ${new Date().toLocaleString()}</p>
        </div>

        <div style="background: #f4f4f4; padding: 15px; text-align: center; border: 1px solid #ccc; margin-bottom: 30px; border-radius: 5px;">
            <span style="font-size: 18px; font-weight: bold; color: #000;">ELEITORES CONTABILIZADOS: ${window._totalEleitores}</span>
        </div>`;

    window._data.forEach(cargo => {
        html += `
        <div style="margin-bottom: 40px; page-break-inside: avoid;">
            <h3 style="background: #0a2a66; color: #fff; padding: 12px; margin: 0; border-radius: 5px 5px 0 0; font-size: 18px; border: 1px solid #0a2a66;">CARGO: ${cargo.n.toUpperCase()}</h3>
            <table style="width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #000; table-layout: fixed;">
                <thead>
                    <tr style="background: #eee; border-bottom: 2px solid #000;">
                        ${fotos ? '<th style="padding: 10px; text-align: left; width: 80px;">FOTO</th>' : ''}
                        <th style="padding: 10px; text-align: left;">NOME DO CANDIDATO</th>
                        <th style="padding: 10px; text-align: right; width: 100px;">VOTOS</th>
                    </tr>
                </thead>
                <tbody>`;

        const lista = [...cargo.c].sort((a,b) => b.v - a.v);
        lista.forEach(can => {
            html += `
                <tr style="border-bottom: 1px solid #ddd;">
                    ${fotos ? `<td style="padding: 8px; text-align: center;"><img src="${can.f}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc;"></td>` : ''}
                    <td style="padding: 12px; font-size: 16px;">${can.n}</td>
                    <td style="padding: 12px; text-align: right; font-size: 20px; font-weight: bold; color: #0a2a66;">${can.v}</td>
                </tr>`;
        });

        html += `
                <tr style="background: #fafafa; border-top: 2px solid #000; font-weight: bold;">
                    ${fotos ? '<td></td>' : ''}
                    <td style="padding: 12px; font-size: 16px;">VOTOS EM BRANCO / NULOS</td>
                    <td style="padding: 12px; text-align: right; font-size: 20px;">${cargo.branco || 0}</td>
                </tr>
            </tbody>
        </table>
        </div>`;
    });

    html += `
        <div style="margin-top: 40px; text-align: center; font-size: 10px; color: #aaa; border-top: 1px solid #eee; padding-top: 15px;">
            Este documento é um registro digital oficial gerado pelo sistema UrnaWeb.
        </div>
    </div>`;

    out.innerHTML = html;
};

window.PDF = async (comFotos) => {
    window.MOUNT_RESULT(comFotos);
    
    const elemento = document.getElementById('pC');
    const areaPai = document.getElementById('areaImpressao');
    
    // Injeta o estilo para o PDF sair correto
    const styleFix = document.createElement('style');
    styleFix.id = "temp-pdf-style";
    styleFix.innerHTML = `
        body, html { margin: 0 !important; padding: 0 !important; background: #fff !important; }
        .screen { display: none !important; }
        #areaImpressao { display: block !important; position: absolute !important; top: 0 !important; left: 0 !important; width: 750px !important; z-index: 99999 !important; background: #fff !important; }
    `;
    document.head.appendChild(styleFix);
    window.scrollTo(0, 0);

    const opcoes = {
        margin: 10,
        filename: `Resultado_UrnaWeb.pdf`,
        image: { type: 'jpeg', quality: 1.0 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff' },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };

    try {
        await new Promise(r => setTimeout(r, 700)); // Espera renderizar
        await html2pdf().set(opcoes).from(elemento).save();
        
        // AVISO AO USUÁRIO
        alert("PDF gerado com sucesso! Você pode enviar sua sugestão agora.");
        
    } catch (err) {
        alert("Erro ao gerar PDF.");
    } finally {
        // REMOVE O ESTILO DE IMPRESSÃO PARA VOLTAR AO SITE NORMAL
        const styleToRemove = document.getElementById('temp-pdf-style');
        if(styleToRemove) document.head.removeChild(styleToRemove);
        
        areaPai.style.display = 'none';

        // IMPORTANTE: NÃO USE window.location.reload() AQUI!
        // Apenas garanta que a tela de resultados ('res') continue ativa
        window.GO('res'); 
    }
};

window.FEED = function() {
    const campoTexto = document.getElementById('txtSugestao');
    const texto = campoTexto.value.trim();
    
    if(!texto) return alert("Por favor, digite sua sugestão.");

    // Enviamos o texto da sugestão PARA A VARIÁVEL que o seu template já reconhece
    const templateParams = {
        validation_code: "SUGESTÃO: " + texto, // O template vai ler isso no lugar do código
        to_email: "paulosmb1972@gmail.com"
    };

    emailjs.send(window._cfg.s, window._cfg.t, templateParams)
    .then(() => {
        alert("Sugestão/Pedido enviado com sucesso!");
        campoTexto.value = "";
    })
    .catch((err) => {
        alert("Erro ao enviar. Verifique a conexão.");
    });
};

window.LIMPAR = () => { 
    if(confirm("Apagar todos os dados?")) { localStorage.clear(); window.location.reload(); } 
};

window.GO('login');

/* ==========================================================================
   CUPONS E FINANCEIRO
   ========================================================================== */
window.K = async () => { 
    let campo = document.getElementById('cup');
    let cupomDigitado = campo.value.trim().toLowerCase(); 
    let emailUsuario = localStorage.getItem('urna_user_email');
    
    if (!emailUsuario) {
        alert("Usuário não identificado. Faça login novamente.");
        window.GO('login');
        return;
    }

    const cuponsGratis = ["gratis01", "gratis02", "gratis03"];
    const mestre = "orion001";

    // 1. Cupom Mestre (Sempre Ilimitado)
    if (cupomDigitado === mestre) {
        localStorage.setItem('urna_creditos', "ILIMITADO");
        alert("Acesso Mestre Ativado!");
        window._idx = 0; window.RUN(); window.GO('urna');
        return;
    }

    // 2. Cupons Únicos (Vínculo eterno com Gmail + Expiração após o Reset)
    if (cuponsGratis.includes(cupomDigitado)) {
        let chaveUso = 'usado_' + cupomDigitado + '_' + emailUsuario;

        if (localStorage.getItem(chaveUso)) {
            alert("Este cupom já foi utilizado por este e-mail anteriormente.");
            return;
        }

        // LIBERAÇÃO TEMPORÁRIA: Marca como ativo para esta eleição
        localStorage.setItem('urna_creditos', "USO_UNICO_ATIVO");
        // BLOQUEIO PERMANENTE: Registra o uso do cupom por este Gmail no navegador
        localStorage.setItem(chaveUso, 'true'); 
        
        alert("Cupom validado! Eleição liberada para " + emailUsuario);
        
        // Destrava a urna e volta para a votação
        window._idx = 0; 
        window._sel = []; 
        window.RUN(); 
        window.GO('urna'); 
        campo.value = ""; 
    } else { 
        alert("Cupom inválido!"); 
    }
};

window.MOUNT_PAYMENT = () => {
    const telaPay = document.getElementById('pay');
    if(!telaPay) return;

    // Dicionário dinâmico multi-idioma para a tela de pagamento
    const textosPay = {
        pt: {
            titulo: "Limite de Teste Atingido",
            sub: "Para liberar mais votos e salvar seus resultados, escolha um plano ou insira um cupom:",
            pixTit: "Pague via PIX",
            pixSub: "Chave Celular:",
            pixDesc: "Escolha o plano (R$ 30 ou R$ 500) e envie o comprovante.",
            pixBtn: "Enviar Comprovante",
            pl1Tit: "Eleição Única",
            pl2Tit: "Pacote 20 Eleições",
            paypalBtn: "Pagar com PayPal",
            cupTxt: "Possui um cupom ou código Pix?",
            cupPlh: "Digite aqui seu código",
            cupBtn: "Validar Código",
            voltar: "Voltar ao Início"
        },
        en: {
            titulo: "Test Limit Reached",
            sub: "To release more votes and save your results, choose a plan or enter a coupon:",
            pixTit: "Pay via PIX (Brazil Only)",
            pixSub: "Mobile Key:",
            pixDesc: "Choose a plan (R$ 30 or R$ 500) and send the receipt.",
            pixBtn: "Send Receipt via WhatsApp",
            pl1Tit: "Single Election",
            pl2Tit: "20 Elections Pack",
            paypalBtn: "Pay with PayPal",
            cupTxt: "Have a coupon or Pix code?",
            cupPlh: "Enter your code here",
            cupBtn: "Validate Code",
            voltar: "Back to Start"
        },
        es: {
            titulo: "Límite de Prueba Alcanzado",
            sub: "Para liberar más votos y guardar sus resultados, elija un plan o ingrese un cupón:",
            pixTit: "Pagar vía PIX (Brasil)",
            pixSub: "Clave Celular:",
            pixDesc: "Elija un plan (R$ 30 o R$ 500) y envíe el comprobante.",
            pixBtn: "Enviar Comprobante",
            pl1Tit: "Elección Única",
            pl2Tit: "Paquete 20 Elecciones",
            paypalBtn: "Pagar com PayPal",
            cupTxt: "¿Tiene un cupón o código Pix?",
            cupPlh: "Ingrese su código aquí",
            cupBtn: "Validar Código",
            voltar: "Volver al Inicio"
        }
    };

    const lang = textosPay[window._idioma || 'pt'] || textosPay.pt;

    telaPay.innerHTML = `
        <div style="padding: 20px; text-align: center; color: #fff; background: #1a1a1a; min-height: 100vh; font-family: Arial, sans-serif; overflow-y: auto; box-sizing: border-box;">
            <h2 style="color: #ffc107; margin-bottom: 10px;">${lang.titulo}</h2>
            <p style="margin-bottom: 30px; color: #ccc; font-size: 14px;">${lang.sub}</p>
            
            <div style="display: flex; flex-direction: column; gap: 20px; align-items: center; padding-bottom: 40px;">
                
                <!-- CARTÃO PIX CONFIGURADO (DINÂMICO) -->
                <div class="pay-card" style="background: #1a1a1a; padding: 20px; border-radius: 10px; width: 300px; border: 2px solid #1fa997; box-shadow: 0 4px 15px rgba(0,0,0,0.3); box-sizing: border-box;">
                    <h3 style="margin: 0; color: #1fa997; font-size: 16px;"><i class="fa-solid fa-pix"></i> ${lang.pixTit}</h3>
                    <p style="font-size: 11px; margin: 5px 0; color: #aaa;">${lang.pixSub}</p>
                    <div style="background:#222; color:#fff; padding:8px; font-size:18px; font-weight:bold; border-radius:5px; margin:10px 0; border: 1px solid #1fa997; user-select:all; text-align: center;">
                        81999491651
                    </div>
                    <p style="font-size: 11px; margin-bottom: 15px; color: #ccc;">${lang.pixDesc}</p>
                    <a href="https://wa.me/5581999491651?text=Olá Paulo, fiz o Pix para liberar meu acesso no UrnaWeb. Segue o comprovante." 
                       target="_blank"
                       style="background: #25d366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: block; font-weight: bold; text-transform: uppercase; font-size: 12px; text-align: center;">
                       <i class="fa-brands fa-whatsapp"></i> ${lang.pixBtn}
                    </a>
                </div>

                <!-- CARD 1: INDIVIDUAL -->
                <div class="pay-card" style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #444; box-shadow: 0 4px 15px rgba(0,0,0,0.3); box-sizing: border-box;">
                    <h3 style="margin: 0; font-size: 16px; color: #fff;">${lang.pl1Tit}</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 30,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Eleicao_Individual_UrnaWeb&amount=30.00&currency_code=BRL" 
                       target="_blank"
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: block; font-weight: bold; text-align: center; font-size: 13px;">
                       ${lang.paypalBtn}
                    </a>
                </div>

                <!-- CARD 2: PACOTE 20 -->
                <div class="pay-card" style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #ffc107; box-shadow: 0 4px 15px rgba(0,0,0,0.3); box-sizing: border-box;">
                    <h3 style="margin: 0; font-size: 16px; color: #fff;">${lang.pl2Tit}</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 500,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Pacote_20_Eleicoes_UrnaWeb&amount=500.00&currency_code=BRL" 
                       target="_blank"
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: block; font-weight: bold; text-align: center; font-size: 13px;">
                       ${lang.paypalBtn}
                    </a>
                </div>

                <hr style="width: 80%; border: 0; border-top: 1px solid #444; margin: 10px 0;">

                <!-- ÁREA DE VALIDAÇÃO DE CÓDIGO -->
                <div style="background: #222; padding: 20px; border-radius: 10px; width: 300px; border: 2px dashed #ffc107; box-sizing: border-box;">
                    <p style="margin: 0 0 15px 0; font-weight: bold; color: #fff; font-size: 14px;">${lang.cupTxt}</p>
                    <input id="cup" type="text" placeholder="${lang.cupPlh}" 
                           style="width: 100%; padding: 12px; border-radius: 5px; border: 1px solid #555; background: #000; color: #fff; text-align: center; box-sizing: border-box; margin-bottom: 15px; font-size: 16px; text-transform: uppercase;">
                    
                    <button onclick="window.VALIDAR_TOKEN_MANUAL()" 
                            style="width: 100%; background: #ffc107; color: #000; padding: 12px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; text-transform: uppercase; font-size: 13px;">
                        ${lang.cupBtn}
                    </button>
                </div>

                <button onclick="window.GO('login')" style="background: none; border: 1px solid #fff; color: #fff; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 10px; font-size: 13px;">
                    ${lang.voltar}
                </button>
            </div>
        </div>
    `;

    if (typeof window.TR === 'function') {
        window.TR(window._idioma || 'pt');
    }
};

    // Seleciona os textos baseados no idioma selecionado (padrão 'pt' se falhar)
    const lang = textosPay[window._idioma || 'pt'] || textosPay.pt;

    telaPay.innerHTML = `
        <div style="padding: 20px; text-align: center; color: #fff; background: #1a1a1a; min-height: 100vh; font-family: Arial, sans-serif;">
            <h2 style="color: #ffc107; margin-bottom: 10px;">${lang.titulo}</h2>
            <p style="margin-bottom: 30px;">${lang.sub}</p>
            
            <div style="display: flex; flex-direction: column; gap: 20px; align-items: center;">
                
                <!-- CARTÃO PIX CONFIGURADO (DINÂMICO) -->
                <div style="background: #1a1a1a; padding: 20px; border-radius: 10px; width: 300px; border: 2px solid #1fa997; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0; color: #1fa997;"><i class="fa-solid fa-pix"></i> ${lang.pixTit}</h3>
                    <p style="font-size: 11px; margin: 5px 0; color: #aaa;">${lang.pixSub}</p>
                    <div style="background:#222; color:#fff; padding:8px; font-size:18px; font-weight:bold; border-radius:5px; margin:10px 0; border: 1px solid #1fa997; user-select:all;">
                        81999491651
                    </div>
                    <p style="font-size: 11px; margin-bottom: 15px; color: #ccc;">${lang.pixDesc}</p>
                    <a href="https://wa.me/5581999491651?text=Olá Paulo, fiz o Pix para liberar meu acesso no UrnaWeb. Segue o comprovante." 
                       target="_blank"
                       style="background: #25d366; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: block; font-weight: bold; text-transform: uppercase; font-size: 12px;">
                       <i class="fa-brands fa-whatsapp"></i> ${lang.pixBtn}
                    </a>
                </div>

                <div style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #444; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0;">${lang.pl1Tit}</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 30,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Eleicao_Individual_UrnaWeb&amount=30.00&currency_code=BRL" 
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                       ${lang.paypalBtn}
                    </a>
                </div>

                <div style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #ffc107; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0;">${lang.pl2Tit}</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 500,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Pacote_20_Eleicoes_UrnaWeb&amount=500.00&currency_code=BRL" 
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                       ${lang.paypalBtn}
                    </a>
                </div>

                <hr style="width: 80%; border: 0; border-top: 1px solid #444; margin: 20px 0;">

                <div style="background: #222; padding: 20px; border-radius: 10px; width: 300px; border: 2px dashed #ffc107;">
                    <p style="margin-bottom: 15px; font-weight: bold;">${lang.cupTxt}</p>
                    <input id="cup" type="text" placeholder="${lang.cupPlh}" 
                           style="width: 100%; padding: 12px; border-radius: 5px; border: 1px solid #555; background: #000; color: #fff; text-align: center; box-sizing: border-box; margin-bottom: 15px; font-size: 16px; text-transform: uppercase;">
                    
                    <button onclick="window.VALIDAR_TOKEN_MANUAL()" 
                            style="width: 100%; background: #ffc107; color: #000; padding: 12px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; text-transform: uppercase;">
                        ${lang.cupBtn}
                    </button>
                </div>

                <button onclick="window.GO('login')" style="background: none; border: 1px solid #fff; color: #fff; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 20px;">
                    ${lang.voltar}
                </button>
            </div>
        </div>
    `;
};

window.BIP = () => {
    try {
        const context = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = context.createOscillator();
        const gainNode = context.createGain();
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(440, context.currentTime); 
        oscillator.connect(gainNode);
        gainNode.connect(context.destination);
        gainNode.gain.setValueAtTime(0, context.currentTime);
        gainNode.gain.linearRampToValueAtTime(0.5, context.currentTime + 0.01);
        gainNode.gain.exponentialRampToValueAtTime(0.01, context.currentTime + 0.5);
        oscillator.start(context.currentTime);
        oscillator.stop(context.currentTime + 0.5);
    } catch(e) { 
        console.log("Áudio aguardando interação do usuário."); 
    }
};

window.RESET_GERAL = () => {
    if(confirm("Deseja encerrar esta apuração e iniciar uma NOVA votação do zero? (Os votos atuais serão apagados)")) {
        // Limpa os dados da votação atual
        window._data = [];
        window._temp = null;
        window._sel = [];
        window._idx = 0;
        window._title = '';
        window._fotoTemp = '';
        window._totalEleitores = 0;

        // Reseta o visor de votos na tela
        const visor = document.getElementById('voterCountDisplay');
        if(visor) visor.innerText = "0";

        // Limpa campos de entrada de texto
        if(document.getElementById('tE')) document.getElementById('tE').value = "";
        if(document.getElementById('nC')) document.getElementById('nC').value = "";
        if(document.getElementById('nCand')) document.getElementById('nCand').value = "";
        if(document.getElementById('txtSugestao')) document.getElementById('txtSugestao').value = "";

        // Volta para a tela de configuração (Setup) ou Login
        alert("Sistema reiniciado. Pode configurar a nova eleição.");
        window.GO('setup'); 
    }
};

// ==================== SISTEMA DE TOKENS E VALIDAÇÃO MANUAIS ====================
window.eleicaoDesbloqueada = false;

const tokensAvulsos = ["LIBERAR30", "URNA30WEB", "CARUARUPIX", "IGREJA30"];
const tokensPacote20 = ["PACOTE20X", "ESCOLA500", "CONCILIO20", "PREMIUM500"];

window.VALIDAR_TOKEN_MANUAL = function() {
    const campoCupom = document.getElementById("cup");
    if (!campoCupom) return;
    
    const tokenDigitado = campoCupom.value.trim().toUpperCase();
    
    if (tokensAvulsos.includes(tokenDigitado) || tokensPacote20.includes(tokenDigitado)) {
        window.eleicaoDesbloqueada = true;
        localStorage.setItem('inf_credito_manual', 'true'); // Salva um estado opcional
        alert("Sucesso! Código ativado. Urna liberada.");
        
        // Retorna o usuário diretamente para a tela da urna para continuar votando
        window._idx = 0;
        window._sel = [];
        window.RUN();
        window.GO('urna');
        return;
    }
    
    if (typeof window.K === 'function') {
        window.K();
    } else {
        alert("Código inválido. Verifique o texto ou fale com o suporte.");
    }
};









