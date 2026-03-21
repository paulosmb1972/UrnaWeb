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

window.MOUNT_RESULT = (fotos) => {
    document.getElementById('pdf_h1').innerText = window._title.toUpperCase();
    let out = document.getElementById('pC'); 
    
    // Estilo do container de resultados
    out.style.color = "#000";
    out.style.padding = "20px";
    out.style.backgroundColor = "#fff";

    let html = `<div style="text-align:center; margin-bottom:20px; border-bottom:2px solid #0a2a66; padding-bottom:10px;">
                    <h2 style="margin:0; color:#0a2a66;">RELATÓRIO DE APURAÇÃO</h2>
                    <b style="font-size:18px;">TOTAL DE ELEITORES: ${window._totalEleitores}</b>
                </div>`;
    
    window._data.forEach(cargo => {
        html += `<div style="margin-top:30px;">
                    <h3 style="background:#0a2a66; color:#fff; padding:8px; border-radius:5px;">${cargo.n.toUpperCase()}</h3>
                    <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                        <thead>
                            <tr style="border-bottom:2px solid #333; text-align:left;">
                                ${fotos ? '<th style="padding:10px;">Foto</th>' : ''}
                                <th style="padding:10px;">Candidato</th>
                                <th style="padding:10px; text-align:right;">Votos</th>
                            </tr>
                        </thead>
                        <tbody>`;
        
        // Ordena candidatos por votos
        const candidatosOrdenados = [...cargo.c].sort((a,b) => b.v - a.v);
        
        candidatosOrdenados.forEach(can => { 
            html += `<tr style="border-bottom:1px solid #ddd;">
                        ${fotos ? `<td style="padding:5px;"><img src="${can.f}" style="width:50px; height:50px; object-fit:cover; border-radius:5px;"></td>` : ''}
                        <td style="padding:10px; font-size:16px;">${can.n}</td>
                        <td style="padding:10px; text-align:right; font-size:18px;"><b>${can.v}</b></td>
                    </tr>`; 
        });

        // Adiciona Votos em Branco
        html += `<tr style="background:#f2f2f2; font-weight:bold;">
                    ${fotos ? '<td></td>' : ''}
                    <td style="padding:10px;">VOTOS EM BRANCO</td>
                    <td style="padding:10px; text-align:right;">${cargo.branco || 0}</td>
                 </tr>
                </tbody>
            </table>
        </div>`;
    });

    out.innerHTML = html;
};

window.FEED = function() {
    const texto = document.getElementById('txtSugestao').value;
    if(!texto) return alert("Por favor, digite sua sugestão.");

    // Usa as configurações do window._cfg definidas no config.js
    emailjs.send(window._cfg.s, window._cfg.t, {
        message: "SUGESTÃO URNAWEB: " + texto,
        to_email: localStorage.getItem('urna_user_email') || "paulosmb1972@gmail.com"
    }).then(() => {
        alert("Sugestão/Pedido enviado com sucesso!");
        document.getElementById('txtSugestao').value = "";
    }).catch((err) => {
        alert("Erro ao enviar. Verifique o EmailJS.");
    });
};

window.PDF = (fotos) => {
    window.MOUNT_RESULT(fotos);
    const area = document.getElementById('areaImpressao');
    area.style.display = 'block'; // Garante que está visível para o script ler

    const opt = {
        margin: [10, 10, 10, 10],
        filename: `Resultado_${window._title}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, logging: false, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };

    // Aguarda 800ms para renderizar as imagens antes de salvar
    setTimeout(() => {
        html2pdf().set(opt).from(area).save().then(() => {
            // Se quiser ocultar a área de impressão após salvar, descomente a linha abaixo
            // area.style.display = 'none';
        });
    }, 800);
};

window.LIMPAR = () => { 
    if(confirm("Apagar todos os dados?")) { localStorage.clear(); window.location.reload(); } 
};

window.GO('login');












