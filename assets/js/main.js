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
   NAVEGAÇÃO E IDENTIDADE DO APARELHO
   ========================================================================== */
window.GO = (id) => {
    if(id === 'login') { 
        localStorage.removeItem('urna_vault'); 
        window._data = []; window._sel = []; window._idx = 0; window._totalEleitores = 0; 
    }
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if(target) target.classList.add('active');
    if(window.TR) window.TR(window._idioma);
};

// Captura Identidade Digital (Prevenção de Fraudes)
window.CAPTURA_DADOS = async () => {
    try {
        const r = await fetch('https://api.ipify.org?format=json');
        const d = await r.json();
        localStorage.setItem('_u_secure_hash', btoa(d.ip));
    } catch (e) {}
    
    const idUnico = btoa([navigator.userAgent, screen.colorDepth].join('|')).substring(0, 16);
    localStorage.setItem('_dev_id', idUnico);
};
window.CAPTURA_DADOS();

/* ==========================================================================
   AUTENTICAÇÃO E SEGURANÇA (TOKEN)
   ========================================================================== */
window.V = async function() { 
    let e = document.getElementById('uE').value.trim().toLowerCase(); 
    if(!e.endsWith('@gmail.com')) return alert("Use um e-mail @gmail.com válido!"); 
    
    localStorage.setItem('urna_user_email', e); 
    let btn = document.getElementById('L2'); 
    btn.disabled = true; btn.innerText = "GERANDO TOKEN..."; 

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
        alert("Falha ao enviar e-mail. Verifique sua conexão."); 
    } finally { 
        btn.disabled = false; window.TR(window._idioma); 
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

/* ==========================================================================
   LOGICA DE CRÉDITOS E TRAVAS
   ========================================================================== */
window.START_VOTE_PROCESS = async () => {
    let creditos = parseInt(localStorage.getItem('urna_creditos') || "0");

    // Consome crédito apenas se tiver (usuários pagantes)
    if (creditos > 0 && creditos < 900000) {
        localStorage.setItem('urna_creditos', (creditos - 1).toString());
        console.log("Crédito consumido.");
    }

    if (window._temp) { window._data.push(JSON.parse(JSON.stringify(window._temp))); window._temp = null; }
    if (window._data.length === 0) return alert("Adicione candidatos primeiro!");
    
    window._idx = 0;
    window.RUN();
    window.GO('urna');
};

window.NEXT = () => {
    let creditos = parseInt(localStorage.getItem('urna_creditos') || "0");
    
    // Regra Comercial: Trava no 10º voto se não houver saldo
    if (creditos <= 0 && window._totalEleitores >= 10) {
        alert("🔒 LIMITE ALCANÇADO: Adquira um plano para continuar recebendo votos.");
        window.GO('pay');
        return;
    }

    window._idx++; 
    if(window._idx < window._data.length) { 
        window.RUN(); 
    } else { 
        window._totalEleitores++;
        document.getElementById('voterCountDisplay').innerText = window._totalEleitores;
        window.BIP(); 
        alert(window._tr[window._idioma].AL_SUC_VOTE); 
        window._idx = 0; window.RUN(); 
    }
};

/* ==========================================================================
   URNA (VOTAÇÃO)
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
        const img = can.f ? `<img src="${can.f}" style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:8px;margin-bottom:10px;">` : `<div style="width:100%;aspect-ratio:1/1;background:#eee;border-radius:8px;display:flex;align-items:center;justify-content:center;margin-bottom:10px;"><i class="fas fa-user fa-2x"></i></div>`;
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
    window.BIP(); 
    window._sel.forEach(i => window._data[window._idx].c[i].v++); 
    window.NEXT();
};

window.BRANCO = () => {
    if(confirm((window._tr[window._idioma].BT_BRANCO || "Votar em Branco") + "?")) {
        window._data[window._idx].branco = (window._data[window._idx].branco || 0) + 1; 
        window.BIP(); window.NEXT();
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
        h += `<tr>${fotos?'<td></td>':''}<td><i>${d.BRANCO_TXT}</i></td><td style="text-align:right"><b>${cargo.branco || 0}</b></td></tr>`;
        out.innerHTML += h + '</tbody></table>';
    });
};

window.CONFIRM_END = () => { 
    if(prompt("Senha (1357):") === "1357") {
        window.MOUNT_RESULT(false); window.GO('res');
    } else alert("Acesso Negado!");
};

window.PDF = (fotos) => {
    window.MOUNT_RESULT(fotos);
    const area = document.getElementById('areaImpressao');
    area.style.display = 'block';
    const opt = {
        margin: 10, filename: `UrnaWeb_${window._title}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff' },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    setTimeout(() => {
        html2pdf().set(opt).from(area).save().then(() => { window.MOUNT_RESULT(false); });
    }, 500);
};

/* ==========================================================================
   CUPONS E FINANCEIRO
   ========================================================================== */
window.K = async () => { 
    let campo = document.getElementById('cup');
    let c = campo.value.trim().toLowerCase(); 
    let cod = btoa(c); 
    
    if (localStorage.getItem('usado_' + cod)) {
        alert("Este cupom já foi usado neste aparelho.");
        return;
    }

    let atuais = parseInt(localStorage.getItem('urna_creditos') || "0");

    if (cod === "b3Jpb24wMDE=") { // orion001
        localStorage.setItem('urna_creditos', "999999");
        alert("Acesso Mestre Ativado.");
    } else if (cod === "cHJvbW8wMQ==") { // promo01
        localStorage.setItem('urna_creditos', (atuais + 1).toString());
        localStorage.setItem('usado_' + cod, 'true');
        alert("1 Eleição Adicionada!");
    } else if (cod === "cHJvbW8wMg==") { // promo02
        localStorage.setItem('urna_creditos', (atuais + 2).toString());
        localStorage.setItem('usado_' + cod, 'true');
        alert("2 Eleições Adicionadas!");
    } else if (cod === "cHJvbW8wMw==") { // promo03
        localStorage.setItem('urna_creditos', (atuais + 3).toString());
        localStorage.setItem('usado_' + cod, 'true');
        alert("3 Eleições Adicionadas!");
    } else {
        alert("Cupom inválido!");
        return;
    }
    window.GO('setup'); campo.value = "";
};

window.LIMPAR = () => { 
    if(confirm("Deseja apagar todos os dados desta urna?")) { 
        localStorage.clear(); window.location.reload(); 
    } 
};

window.GO('login');













