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
    
    // Largura interna de 700px dentro de um wrapper de 800px garante que nada corte
    let html = `
    <div id="pdf-content-wrapper" style="font-family: Arial, sans-serif; color: #000; background: #fff; padding: 40px; width: 750px; box-sizing: border-box; margin: 0;">
        
        <div style="text-align: center; border-bottom: 4px solid #0a2a66; padding-bottom: 20px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 26px; color: #0a2a66;">${window._title.toUpperCase()}</h1>
            <p style="margin: 5px 0; font-size: 14px; color: #333;">RELATÓRIO DE APURAÇÃO DIGITAL</p>
        </div>

        <div style="background: #eee; padding: 15px; text-align: center; margin-bottom: 30px; border-radius: 5px;">
            <b style="font-size: 20px;">TOTAL DE VOTOS COMPUTADOS: ${window._totalEleitores}</b>
        </div>`;

    window._data.forEach(cargo => {
        html += `
        <div style="margin-bottom: 40px; page-break-inside: avoid;">
            <h3 style="background: #0a2a66; color: #fff; padding: 12px; margin: 0; border-radius: 5px 5px 0 0;">CARGO: ${cargo.n.toUpperCase()}</h3>
            <table style="width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #000;">
                <thead>
                    <tr style="background: #ddd;">
                        ${fotos ? '<th style="padding: 10px; text-align: left; width: 80px;">FOTO</th>' : ''}
                        <th style="padding: 10px; text-align: left;">CANDIDATO</th>
                        <th style="padding: 10px; text-align: right; width: 120px;">VOTOS</th>
                    </tr>
                </thead>
                <tbody>`;

        const lista = [...cargo.c].sort((a,b) => b.v - a.v);
        lista.forEach(can => {
            html += `
                <tr style="border-bottom: 1px solid #ccc;">
                    ${fotos ? `<td style="padding: 5px; text-align: center;"><img src="${can.f}" style="width: 60px; height: 60px; object-fit: cover; border: 1px solid #ddd;"></td>` : ''}
                    <td style="padding: 10px; font-size: 18px;">${can.n}</td>
                    <td style="padding: 10px; text-align: right; font-size: 22px; font-weight: bold; color: #0a2a66;">${can.v}</td>
                </tr>`;
        });

        html += `
                <tr style="background: #f9f9f9; border-top: 2px solid #000; font-weight: bold;">
                    ${fotos ? '<td></td>' : ''}
                    <td style="padding: 10px; font-size: 18px;">VOTOS EM BRANCO</td>
                    <td style="padding: 10px; text-align: right; font-size: 22px;">${cargo.branco || 0}</td>
                </tr>
            </tbody>
        </table>
        </div>`;
    });

    html += `</div>`;
    out.innerHTML = html;
};

window.PDF = async (comFotos) => {
    // 1. Gera o conteúdo no HTML
    window.MOUNT_RESULT(comFotos);
    
    const elemento = document.getElementById('pdf-content-wrapper');
    const areaPai = document.getElementById('areaImpressao');
    
    // 2. Torna visível mas fora da tela do usuário
    areaPai.style.display = 'block';
    areaPai.style.position = 'fixed';
    areaPai.style.left = '0';
    areaPai.style.top = '-5000px'; // Joga para longe lá no topo
    areaPai.style.width = '800px'; // Define uma largura fixa para o container pai
    areaPai.style.zIndex = '-9999';

    // 3. Configurações de Captura para evitar cortes
    const opcoes = {
        margin: [10, 5, 10, 5], // Margens: topo, esquerda, baixo, direita
        filename: `Apuracao_UrnaWeb_${new Date().getTime()}.pdf`,
        image: { type: 'jpeg', quality: 1.0 },
        html2canvas: { 
            scale: 2, 
            useCORS: true, 
            backgroundColor: '#ffffff',
            width: 750,       // Captura exatamente 750px de largura
            windowWidth: 800, // Simula um navegador de 800px de largura
            scrollX: 0,
            scrollY: 0
        },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };

    try {
        // 4. Executa a geração
        await html2pdf().set(opcoes).from(elemento).save();
    } catch (err) {
        console.error("Erro PDF:", err);
        alert("Erro ao gerar o relatório.");
    } finally {
        // 5. Limpeza
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












