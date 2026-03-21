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
    window._idx++; 
    if(window._idx < window._data.length) { 
        window.RUN(); 
    } else { 
        window._totalEleitores++;
        document.getElementById('voterCountDisplay').innerText = window._totalEleitores;
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
    
    // Reduzi a largura para 650px para garantir margens de segurança no A4
    let html = `
    <div id="pdf-content-wrapper" style="font-family: Arial, sans-serif; color: #000; background: #fff; padding: 20px; width: 650px; margin: 0 auto; box-sizing: border-box;">
        
        <div style="text-align: center; border-bottom: 3px solid #0a2a66; padding-bottom: 15px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 22px; text-transform: uppercase; color: #0a2a66;">${window._title || "RELATÓRIO DE VOTAÇÃO"}</h1>
            <p style="margin: 5px 0; font-size: 11px; color: #666;">Documento Oficial - Gerado em: ${new Date().toLocaleString()}</p>
        </div>

        <div style="background: #f4f4f4; padding: 12px; text-align: center; border: 1px solid #ddd; margin-bottom: 20px; border-radius: 5px;">
            <span style="font-size: 15px; font-weight: bold; color: #333;">TOTAL DE ELEITORES: ${window._totalEleitores}</span>
        </div>`;

    window._data.forEach(cargo => {
        html += `
        <div style="margin-bottom: 35px; page-break-inside: avoid;">
            <h2 style="background: #0a2a66; color: #fff; padding: 10px; font-size: 16px; margin-bottom: 0; border-radius: 4px 4px 0 0;">CARGO: ${cargo.n.toUpperCase()}</h2>
            <table style="width: 100%; border-collapse: collapse; table-layout: fixed; border: 1px solid #eee;">
                <thead>
                    <tr style="background: #eee; border-bottom: 2px solid #000;">
                        ${fotos ? '<th style="padding: 10px; text-align: left; width: 70px; font-size: 12px;">FOTO</th>' : ''}
                        <th style="padding: 10px; text-align: left; font-size: 12px;">CANDIDATO</th>
                        <th style="padding: 10px; text-align: right; width: 80px; font-size: 12px;">VOTOS</th>
                    </tr>
                </thead>
                <tbody>`;

        const candRank = [...cargo.c].sort((a, b) => b.v - a.v);

        candRank.forEach(can => {
            html += `
            <tr style="border-bottom: 1px solid #eee;">
                ${fotos ? `<td style="padding: 8px;"><img src="${can.f || ''}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px; border: 1px solid #ddd;"></td>` : ''}
                <td style="padding: 10px; font-size: 14px; word-wrap: break-word;">${can.n}</td>
                <td style="padding: 10px; text-align: right; font-weight: bold; font-size: 16px; color: #0a2a66;">${can.v}</td>
            </tr>`;
        });

        html += `
            <tr style="background: #fafafa; border-top: 1px solid #000;">
                ${fotos ? '<td></td>' : ''}
                <td style="padding: 10px; font-size: 14px; font-style: italic;">VOTOS EM BRANCO / NULOS</td>
                <td style="padding: 10px; text-align: right; font-weight: bold; font-size: 16px;">${cargo.branco || 0}</td>
            </tr>
                </tbody>
            </table>
        </div>`;
    });

    html += `
        <div style="margin-top: 40px; text-align: center; font-size: 10px; color: #999; border-top: 1px solid #eee; padding-top: 15px;">
            UrnaWeb Digital - Sistema de Votação Presbiteriana
        </div>
    </div>`;

    out.innerHTML = html;
};

window.PDF = async (comFotos) => {
    // 1. Prepara os dados
    window.MOUNT_RESULT(comFotos);
    
    // 2. Localiza o elemento
    const elemento = document.getElementById('pC');
    const areaPai = document.getElementById('areaImpressao');
    
    // 3. Força visibilidade temporária para o print
    areaPai.style.display = 'block';
    areaPai.style.position = 'absolute';
    areaPai.style.left = '-9999px'; // Move para fora da tela do usuário mas deixa visível para a IA
    areaPai.style.top = '0';

    // 4. Configuração Robusta
    const opcoes = {
        margin: [10, 10, 10, 10],
        filename: `Apuracao_${window._title.replace(/\s+/g, '_')}.pdf`,
        image: { type: 'jpeg', quality: 1.0 },
        html2canvas: { 
            scale: 2, 
            useCORS: true, 
            letterRendering: true,
            backgroundColor: '#ffffff',
            scrollY: 0
        },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };

    // 5. Execução com tratamento de erro
    try {
        await html2pdf().set(opcoes).from(elemento).save();
    } catch (err) {
        console.error("Erro no PDF:", err);
        alert("Erro ao gerar PDF. Tente novamente.");
    } finally {
        // Esconde novamente após o processo
        areaPai.style.display = 'none';
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












