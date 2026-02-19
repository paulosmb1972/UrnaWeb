console.log("Main JS carregado!");
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

// Bloqueio de Inspeção (Opcional, mas estava no seu original)
document.addEventListener('contextmenu', e => e.preventDefault());
document.onkeydown = function(e) { 
    if (e.keyCode == 123 || (e.ctrlKey && e.shiftKey && (e.keyCode == 73 || e.keyCode == 74)) || (e.ctrlKey && e.keyCode == 85)) return false; 
};

/* ==========================================================================
   NAVEGAÇÃO E UTILITÁRIOS
   ========================================================================== */
window.GO = (id) => {
    if(id === 'login') { 
        localStorage.removeItem('urna_vault'); 
        window._data = []; 
        window._sel = []; 
        window._idx = 0; 
        window._totalEleitores = 0; 
    }
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    if(window.TR) window.TR(window._idioma);
};

window.LIMPAR = () => { 
    if(confirm(window._tr[window._idioma].B_CACHE)) { 
        localStorage.clear(); 
        window.location.reload(true); 
    } 
};

window.BIP = () => {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator(); const g = ctx.createGain();
        osc.type = 'square'; osc.frequency.setValueAtTime(440, ctx.currentTime);
        g.gain.setValueAtTime(0.1, ctx.currentTime);
        osc.connect(g); g.connect(ctx.destination);
        osc.start(); osc.stop(ctx.currentTime + 0.7); 
    } catch(e){}
};

/* ==========================================================================
   AUTENTICAÇÃO E SEGURANÇA
   ========================================================================== */
window.V = async function() { 
    let e = document.getElementById('uE').value.trim().toLowerCase(); 
    if(!e.endsWith('@gmail.com')) return alert(window._tr[window._idioma].AL_ERR_MAIL || "Use Gmail!"); 
    
    localStorage.setItem('urna_user_email', e); 
    let btn = document.getElementById('L2'); 
    btn.disabled = true; btn.innerText = "..."; 

    try { 
        let r = await fetch(window._cfg.u + '/?email=' + encodeURIComponent(e)); 
        let d = await r.json(); 
        if(d.pay_required === true || (d.count !== undefined && Number(d.count) >= 3)) { 
            window.GO('pay'); 
            return; 
        } 
        let cod = (d.codigo || d).toString().trim(); 
        localStorage.setItem('urna_vault', cod); 
        await emailjs.send(window._cfg.s, window._cfg.t, { to_email: e, validation_code: cod }, window._cfg.k); 
        alert(window._tr[window._idioma].AL_COD_ENV || "Enviado!"); 
        window.GO('verify'); 
    } catch(err) { 
        alert("Erro de conexão com o servidor de segurança."); 
    } finally { 
        btn.disabled = false; 
        window.TR(window._idioma); 
    } 
};

window.C = () => { 
    let d = document.getElementById('iC').value.trim();
    if(d === (localStorage.getItem('urna_vault') || "").trim()) window.GO('setup'); 
    else alert(window._tr[window._idioma].AL_INC); 
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

/* ==========================================================================
   CORREÇÃO: ADICIONAR E CONSOLIDAR
   ========================================================================== */

/* ==========================================================================
   CORREÇÃO DE FLUXO: ADICIONAR, SALVAR E INICIAR
   ========================================================================== */

window.A = () => {
    const cargo = document.getElementById('nC').value.trim();
    const nome = document.getElementById('nCand').value.trim();

    if (!cargo || !nome) {
        alert(window._tr[window._idioma].AL_FALTA || "Preencha cargo e nome!");
        return;
    }

    // Inicializa o cargo temporário se ele não existir
    if (!window._temp) {
        window._temp = { n: cargo, c: [], branco: 0 };
    }

    // Adiciona o candidato ao cargo atual
    window._temp.c.push({ n: nome, v: 0, f: window._fotoTemp });

    // Atualiza a lista visual (Preview)
    const lista = document.getElementById('listaTemporaria');
    const item = document.createElement('div');
    item.style = "padding: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 13px;";
    item.innerHTML = `👤 <b>${nome}</b> <small>(${cargo})</small>`;
    lista.appendChild(item);

    // Limpa campos para o próximo candidato do MESMO cargo
    document.getElementById('nCand').value = '';
    window._fotoTemp = '';
    document.getElementById('imgPrev').style.display = 'none';
};

window.SAVE = () => {
    if (!window._temp || window._temp.c.length === 0) {
        alert("Adicione candidatos antes de salvar o cargo!");
        return;
    }

    // Move do temporário para o banco de dados oficial da eleição
    window._data.push(JSON.parse(JSON.stringify(window._temp))); 
    
    // Reseta o temporário e a interface para um NOVO cargo (ex: Prefeito -> Vereador)
    window._temp = null;
    document.getElementById('nC').value = '';
    document.getElementById('listaTemporaria').innerHTML = '';
    
    alert("Cargo consolidado com sucesso!");
};

window.START_VOTE_PROCESS = async () => {
    // Caso o usuário tenha esquecido de clicar em SALVAR, mas tenha candidatos no TEMP
    if (window._temp && window._temp.c.length > 0) {
        window._data.push(JSON.parse(JSON.stringify(window._temp)));
        window._temp = null;
    }

    if (window._data.length === 0) {
        alert("Nenhum cargo configurado. Adicione candidatos e salve o cargo primeiro.");
        return;
    }

    // Incremento de segurança (Opcional)
    try {
        let email = localStorage.getItem('urna_user_email');
        if (email && window._cfg) {
            fetch(`${window._cfg.u}/increment?email=${encodeURIComponent(email)}`);
        }
    } catch (e) {}

    window._idx = 0;
    window.RUN();
    window.GO('urna');
};

window.RUN = () => {
    // 1. Localiza os elementos da Urna
    const displayCargo = document.getElementById('uT');
    const grid = document.getElementById('gridUrna');
    
    // Verifica se os elementos existem antes de continuar
    if (!displayCargo || !grid) {
        console.error("Erro: Elementos da urna não encontrados no HTML.");
        return;
    }

    // 2. Pega os dados do cargo atual
    const cargoAtual = window._data[window._idx];
    if (!cargoAtual) {
        console.error("Erro: Dados do cargo não encontrados.");
        return;
    }

    // 3. Atualiza o título do cargo
    displayCargo.innerText = cargoAtual.n.toUpperCase();
    
    // 4. Limpa o grid e reseta a seleção
    grid.innerHTML = '';
    window._sel = [];

    // 5. Renderiza os cards dos candidatos
    cargoAtual.c.forEach((can, i) => {
        const card = document.createElement('div');
        card.className = 'cand-card';
        
        // Estilo inline para garantir que apareça (pode ser movido para o CSS depois)
        card.style.cssText = `
            background: white;
            color: black;
            padding: 15px;
            border-radius: 12px;
            text-align: center;
            cursor: pointer;
            border: 4px solid transparent;
            transition: 0.2s;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        `;

        // Conteúdo do Card (Foto + Nome)
        const imgHtml = can.f ? `<img src="${can.f}" style="width:100%; aspect-ratio:1/1; object-fit:cover; border-radius:8px; margin-bottom:10px;">` : `<div style="width:100%; aspect-ratio:1/1; background:#eee; border-radius:8px; display:flex; align-items:center; justify-content:center; margin-bottom:10px;"><i class="fas fa-user fa-2x" style="color:#ccc;"></i></div>`;
        
        card.innerHTML = `${imgHtml}<b style="display:block; font-size:14px; text-transform:uppercase;">${can.n}</b>`;

        // Evento de Seleção
        card.onclick = () => {
            if (window._sel.includes(i)) {
                window._sel = window._sel.filter(item => item !== i);
                card.style.borderColor = "transparent";
                card.style.background = "white";
            } else if (window._sel.length < window._maxVotos) {
                window._sel.push(i);
                card.style.borderColor = "var(--success)";
                card.style.background = "rgba(46, 204, 113, 0.1)";
            }
        };

        grid.appendChild(card);
    });
};

window.VOTE = () => { 
    if(!window._sel.length) return alert("Selecione um candidato ou vote em Branco."); 
    window.BIP(); 
    window._sel.forEach(i => window._data[window._idx].c[i].v++); 
    window.NEXT();
};

window.BRANCO = () => {
    let cargo = window._data[window._idx];
    // Pergunta se confirma o voto em branco usando o idioma atual
    if(confirm((window._tr[window._idioma].BT_BRANCO || "Votar em Branco") + "?")) {
        if(cargo.branco === undefined) cargo.branco = 0; 
        cargo.branco++; 
        window.BIP(); 
        window.NEXT();
    }
};

window.NEXT = () => {
    window._idx++; 
    if(window._idx < window._data.length) { 
        window.RUN(); 
    } else { 
        window._totalEleitores++;
        document.getElementById('voterCountDisplay').innerText = window._totalEleitores;
        alert(window._tr[window._idioma].AL_SUC_VOTE); 
        window._idx = 0; 
        window.RUN(); 
    }
};

/* ==========================================================================
   RESULTADOS E EXPORTAÇÃO
   ========================================================================== */
window.MOUNT_RESULT = (fotos) => {
    let d = window._tr[window._idioma];
    document.getElementById('pdf_h1').innerText = window._title.toUpperCase();
    document.getElementById('pdf-audit').innerText = d.AUDIT + ": " + new Date().toLocaleString();
    let out = document.getElementById('pC'); 
    out.innerHTML = `<div style="text-align:center; margin-bottom:15px; border-bottom:1px solid #000; padding-bottom:10px;"><b>${d.PDF_TOTAL}: ${window._totalEleitores}</b></div>`;
    
    window._data.forEach(cargo => {
        let h = `<h3>${cargo.n.toUpperCase()}</h3><table class="pdf-table"><thead><tr>${fotos?'<th style="width:50px">Foto</th>':''}<th>${d.PDF_CAND}</th><th style="text-align:right">${d.PDF_VOT}</th></tr></thead><tbody>`;
        cargo.c.sort((a,b) => b.v - a.v).forEach(can => { 
            h += `<tr>${fotos ? `<td><img src="${can.f}" style="width:40px;height:40px;object-fit:cover;border-radius:4px;"></td>` : ''}<td>${can.n}</td><td style="text-align:right"><b>${can.v}</b></td></tr>`; 
        });
        if(cargo.branco > 0) h += `<tr>${fotos?'<td></td>':''}<td><i>${d.BRANCO_TXT}</i></td><td style="text-align:right"><b>${cargo.branco}</b></td></tr>`;
        out.innerHTML += h + '</tbody></table>';
    });
};

window.CONFIRM_END = () => { 
    let pass = window._idioma === 'pt' ? "Senha (1357):" : "Password (1357):";
    if(prompt(pass) === "1357") {
        window.MOUNT_RESULT(false); 
        window.GO('res');
    } else {
        alert(window._tr[window._idioma].AL_INC);
    }
};

window.MOUNT_RESULT = (fotos) => {
    let d = window._tr[window._idioma];
    document.getElementById('pdf_h1').innerText = window._title.toUpperCase();
    document.getElementById('pdf-audit').innerText = d.AUDIT + ": " + new Date().toLocaleString();
    let out = document.getElementById('pC'); 
    out.innerHTML = `<div style="text-align:center; margin-bottom:15px; border-bottom:1px solid #000; padding-bottom:10px;"><b>${d.PDF_TOTAL}: ${window._totalEleitores}</b></div>`;
    
    window._data.forEach(cargo => {
        let h = `<h3>${cargo.n.toUpperCase()}</h3><table class="pdf-table"><thead><tr>${fotos?'<th style="width:50px">Foto</th>':''}<th>${d.PDF_CAND}</th><th style="text-align:right">${d.PDF_VOT}</th></tr></thead><tbody>`;
        
        // Candidatos
        cargo.c.sort((a,b) => b.v - a.v).forEach(can => { 
            h += `<tr>${fotos ? `<td><img src="${can.f}" style="width:40px;height:40px;object-fit:cover;border-radius:4px;"></td>` : ''}<td>${can.n}</td><td style="text-align:right"><b>${can.v}</b></td></tr>`; 
        });

        // Votos em Branco (Garante que apareça mesmo que seja 0)
        let totalBrancos = cargo.branco || 0;
        h += `<tr>${fotos?'<td></td>':''}<td><i>${d.BRANCO_TXT || 'Votos em Branco'}</i></td><td style="text-align:right"><b>${totalBrancos}</b></td></tr>`;
        
        out.innerHTML += h + '</tbody></table>';
    });
};
/* ==========================================================================
   FINANCEIRO E FEEDBACK
   ========================================================================== */
window.K = async () => { 
    let c = document.getElementById('cup').value.trim().toLowerCase(); 
    let email = localStorage.getItem('urna_user_email');
    if(btoa(c) === "b3Jpb24wMDE=" || btoa(c) === "bWFpczNncmF0aXM=") { 
        if(email) await fetch(window._cfg.u + '/use_coupon?email=' + encodeURIComponent(email));
        alert("Crédito ativado!"); window.GO('setup'); 
    } else alert("Cupom Inválido!"); 
};

window.FEED = () => { 
    let m = document.getElementById('txtSugestao').value.trim(); 
    if(!m) return alert("Escreva algo antes de enviar."); 
    let templateParams = { 
        to_email: 'paulosmb1972@gmail.com', 
        validation_code: m, 
        user_email: localStorage.getItem('urna_user_email'), 
        election_title: window._title 
    };
    emailjs.send(window._cfg.s, window._cfg.t, templateParams, window._cfg.k).then(() => { 
        alert("Mensagem enviada com sucesso!"); 
        document.getElementById('txtSugestao').value = ''; 
    });
};

// Start
window.GO('login');







