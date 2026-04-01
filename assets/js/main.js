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
    window.BIP(); // Som de confirmação
    window._idx++; 

    // Se ainda houver cargos para o mesmo eleitor votar (Ex: de Presbítero para Diácono)
    if(window._idx < window._data.length) { 
        window.RUN(); 
    } else { 
        // Eleitor terminou todos os cargos da sua vez
        window._totalEleitores++;
        
        const visor = document.getElementById('voterCountDisplay');
        if(visor) visor.innerText = window._totalEleitores;

        // TRAVA DE SEGURANÇA: Se não houver créditos e já tiver 10 votos
        let temCredito = localStorage.getItem('urna_creditos') === "999999";

        if(!temCredito && window._totalEleitores >= 10) {
            alert("Limite de teste atingido (10 eleitores). Insira seu cupom para continuar registrando votos.");
            window.MOUNT_PAYMENT();
            window.GO('pay');
            // O sistema "para" aqui e não reseta o _idx. 
            // O reset só acontecerá quando o Cupom for validado na função window.K acima.
            return; 
        }

        // Se tiver crédito ou for menos de 10 eleitores, reseta o ciclo normalmente
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
    
    const cuponsGratis = ["gratis01", "gratis02", "gratis03"];
    const mestre = "orion001";

    if (cupomDigitado === mestre || cuponsGratis.includes(cupomDigitado)) {
        // Validação de uso único para os gratuitos
        if (cupomDigitado !== mestre && localStorage.getItem('usado_' + cupomDigitado)) {
            alert("Este cupom já foi utilizado anteriormente neste aparelho.");
            return;
        }

        // 1. Libera créditos no sistema
        localStorage.setItem('urna_creditos', "999999");
        if (cupomDigitado !== mestre) localStorage.setItem('usado_' + cupomDigitado, 'true');

        alert("Cupom validado! Destravando urna...");

        // 2. DESTRAVAMENTO REAL:
        // Resetamos o índice de cargos para o início e limpamos a seleção
        window._idx = 0; 
        window._sel = []; 
        
        // 3. Redesenhamos a tela com o primeiro cargo configurado
        window.RUN(); 
        
        // 4. Voltamos para a tela da Urna
        window.GO('urna'); 
        campo.value = ""; 
    } else { 
        alert("Cupom inválido!"); 
    }
};

window.MOUNT_PAYMENT = () => {
    const telaPay = document.getElementById('pay');
    if(!telaPay) return;

    telaPay.innerHTML = `
        <div style="padding: 20px; text-align: center; color: #fff; background: #1a1a1a; min-height: 100vh; font-family: Arial, sans-serif;">
            <h2 style="color: #ffc107; margin-bottom: 10px;">Limite de Teste Atingido</h2>
            <p style="margin-bottom: 30px;">Para liberar mais votos e salvar seus resultados, escolha um plano ou insira um cupom:</p>
            
            <div style="display: flex; flex-direction: column; gap: 20px; align-items: center;">
                
                <div style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #444; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0;">Eleição Única</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 30,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Eleicao_Individual_UrnaWeb&amount=30.00&currency_code=BRL" 
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                       Pagar com PayPal
                    </a>
                </div>

                <div style="background: #333; padding: 20px; border-radius: 10px; width: 300px; border: 1px solid #ffc107; box-shadow: 0 4px 15px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0;">Pacote 20 Eleições</h3>
                    <p style="font-size: 28px; color: #28a745; font-weight: bold; margin: 10px 0;">R$ 500,00</p>
                    <a href="https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=paulosmb1972@gmail.com&item_name=Pacote_20_Eleicoes_UrnaWeb&amount=500.00&currency_code=BRL" 
                       style="background: #0070ba; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                       Pagar com PayPal
                    </a>
                </div>

                <hr style="width: 80%; border: 0; border-top: 1px solid #444; margin: 20px 0;">

                <div style="background: #222; padding: 20px; border-radius: 10px; width: 300px; border: 2px dashed #ffc107;">
                    <p style="margin-bottom: 15px; font-weight: bold;">Possui um cupom?</p>
                    <input id="cup" type="text" placeholder="Digite aqui (ex: orion001)" 
                           style="width: 100%; padding: 12px; border-radius: 5px; border: 1px solid #555; background: #000; color: #fff; text-align: center; box-sizing: border-box; margin-bottom: 15px; font-size: 16px;">
                    
                    <button onclick="window.K()" 
                            style="width: 100%; background: #ffc107; color: #000; padding: 12px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; text-transform: uppercase;">
                        Validar Cupom
                    </button>
                </div>

                <button onclick="window.GO('login')" style="background: none; border: 1px solid #fff; color: #fff; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin-top: 20px;">
                    Voltar ao Início
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
        // Frequência de 440Hz (Lá) para um som mais clássico de urna
        oscillator.frequency.setValueAtTime(440, context.currentTime); 
        
        oscillator.connect(gainNode);
        gainNode.connect(context.destination);

        gainNode.gain.setValueAtTime(0, context.currentTime);
        gainNode.gain.linearRampToValueAtTime(0.5, context.currentTime + 0.01);
        gainNode.gain.exponentialRampToValueAtTime(0.01, context.currentTime + 0.5);

        oscillator.start(context.currentTime);
        oscillator.stop(context.currentTime + 0.5); // Duração estendida para meio segundo
    } catch(e) { 
        console.log("Áudio aguardando interação do usuário."); 
    }
};










