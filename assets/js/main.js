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
    const target = document.getElementById(id);
    if(target) target.classList.add('active');
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

window.A = () => {
    const cargo = document.getElementById('nC').value.trim();
    const nome = document.getElementById('nCand').value.trim();
    if (!cargo || !nome) return alert("Preencha cargo e nome!");
    if (!window._temp) window._temp = { n: cargo, c: [], branco: 0 };
    window._temp.c.push({ n: nome, v: 0, f: window._fotoTemp });
    const lista = document.getElementById('listaTemporaria');
    lista.innerHTML += `<div style="padding:5px;border-bottom:1px solid rgba(255,255,255,0.1)">👤 <b>${nome}</b></div>`;
    document.getElementById('nCand').value = '';
    window._fotoTemp = '';
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

window.START_VOTE_PROCESS = async () => {
    if (window._temp) { window._data.push(JSON.parse(JSON.stringify(window._temp))); window._temp = null; }
    if (window._data.length === 0) return alert("Configure a eleição primeiro!");
    window._idx = 0;
    window.RUN();
    window.GO('urna');
};

/* ==========================================================================
   URNA (VOTAÇÃO)
   ========================================================================== */
window.RUN = () => {
    const displayCargo = document.getElementById('uT');
    const grid = document.getElementById('gridUrna');
    const cargoAtual = window._data[window._idx];
    displayCargo.innerText = cargoAtual.n.toUpperCase();
    grid.innerHTML = '';
    window._sel = [];

    cargoAtual.c.forEach((can, i) => {
        const card = document.createElement('div');
        card.className = 'cand-card';
        card.style.cssText = `background:white;color:black;padding:15px;border-radius:12px;text-align:center;cursor:pointer;border:4px solid transparent;`;
        const imgHtml = can.f ? `<img src="${can.f}" style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:8px;margin-bottom:10px;">` : `<div style="width:100%;aspect-ratio:1/1;background:#eee;border-radius:8px;display:flex;align-items:center;justify-content:center;margin-bottom:10px;"><i class="fas fa-user fa-2x" style="color:#ccc;"></i></div>`;
        card.innerHTML = `${imgHtml}<b>${can.n}</b>`;
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
    if(!window._sel.length) return alert("Selecione um candidato ou vote em Branco."); 
    window.BIP(); 
    window._sel.forEach(i => window._data[window._idx].c[i].v++); 
    window.NEXT();
};

window.BRANCO = () => {
    let cargo = window._data[window._idx];
    if(confirm((window._tr[window._idioma].BT_BRANCO || "Voto em Branco") + "?")) {
        cargo.branco = (cargo.branco || 0) + 1; 
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
   RESULTADOS E PDF
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
        // Votos em Branco
        let brancos = cargo.branco || 0;
        h += `<tr>${fotos?'<td></td>':''}<td><i>${d.BRANCO_TXT || 'Brancos'}</i></td><td style="text-align:right"><b>${brancos}</b></td></tr>`;
        out.innerHTML += h + '</tbody></table>';
    });
};

window.CONFIRM_END = () => { 
    let pass = window._idioma === 'pt' ? "Senha (1357):" : "Password (1357):";
    if(prompt(pass) === "1357") {
        window.MOUNT_RESULT(false); 
        window.GO('res');
    } else alert("Acesso Negado!");
};

window.PDF = (fotos) => {
    window.MOUNT_RESULT(fotos);
    const area = document.getElementById('areaImpressao');
    const opt = {
        margin: 10,
        filename: 'Resultado_UrnaWeb.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    html2pdf().set(opt).from(area).save().then(() => {
        window.MOUNT_RESULT(false);
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
    let params = { to_email: 'paulosmb1972@gmail.com', validation_code: m, user_email: localStorage.getItem('urna_user_email'), election_title: window._title };
    emailjs.send(window._cfg.s, window._cfg.t, params, window._cfg.k).then(() => { 
        alert("Enviado!"); 
        document.getElementById('txtSugestao').value = ''; 
    });
};

window.GO('login');
