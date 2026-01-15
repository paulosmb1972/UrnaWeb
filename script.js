// CONFIGURAÇÕES GERAIS
emailjs.init("_PKL4Oj92o48KurSF");
const _MK = "ORION001"; 
const _MK2 = "ORION002"; 
const _CK = "MAIS3GRATIS";
const BACKEND_URL = "https://urnaweb-backend.paulosmb1972.workers.dev";

let lang = 'pt';
let userEmail = "";
let codigoEmail = "";
let eleicaoData = [];
let cargoTemp = null;
let fotoBase64 = "";
let votosSelecionados = [];
let indiceCargoAtual = 0;
let tituloEleicaoGlobal = "";

// DICIONÁRIO DE TRADUÇÃO
const i18n = {
    pt: {
        tLogin: "Acesso ao Sistema", hEmail: "E-mail para validar créditos:", pEmail: "Seu Gmail...", btnVerifyEmail: "Entrar", pInfo: "3 eleições iniciais gratuitas.",
        tLimit: "Créditos Esgotados", tPayOption: "Eleição Individual", tPayOption20: "Pacote 20 Eleições", btnPay: "Pagar R$ 30,00", btnPay20: "Pagar R$ 500,00", hCoupon: "Possui um cupom?", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Voltar",
        tConfirm: "Verifique seu E-mail", hCode: "Código de 6 dígitos enviado:", pCode: "Código", btnConfirm: "Confirmar",
        tGeneral: "Início da Eleição", hElectionName: "Nome da eleição:", pElectionName: "Ex: Condomínio Orion", btnNextStep: "Próximo",
        tCargo: "Configurar Cargo", hCargoName: "Nome da função:", pCargoName: "Ex: Síndico", hVotosQtd: "Votos por eleitor:", btnAddCand: "Adicionar Candidatos",
        hCandName: "Nome do candidato:", pCandName: "Nome completo", hCandFoto: "Foto do candidato:", btnToList: "Adicionar", btnSaveCargo: "Salvar Cargo", btnStartVote: "INICIAR VOTAÇÃO 🗳️",
        btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "ENCERRAR ELEIÇÃO", tResults: "Resultado", btnDownload: "Baixar PDF 📄", btnFinish: "Finalizar e Sair",
        tFeedback: "Sugestões ou Pedidos", pFeedback: "Sua sugestão...", btnSendFeedback: "Enviar Sugestão",
        msgSelect: "Selecione um candidato.", msgVoteOk: "Voto computado!", msgTitleErr: "Põe um nome!", msgCargoErr: "Põe um cargo!", msgFeedOk: "Sugestão enviada!"
    },
    en: {
        tLogin: "System Access", hEmail: "Email for credits:", pEmail: "Your Gmail...", btnVerifyEmail: "Enter", pInfo: "3 initial free elections.",
        tLimit: "Credits Exhausted", tPayOption: "Single Election", tPayOption20: "20 Elections Pack", btnPay: "Pay R$ 30.00", btnPay20: "Pay R$ 500.00", hCoupon: "Have a coupon?", pCoupon: "Code", btnCoupon: "Validate", btnBack: "Back",
        tConfirm: "Check Email", hCode: "6-digit code sent:", pCode: "Code", btnConfirm: "Confirm",
        tGeneral: "Election Setup", hElectionName: "Election name:", pElectionName: "e.g. Orion Condo", btnNextStep: "Next",
        tCargo: "Position Setup", hCargoName: "Position name:", pCargoName: "e.g. Trustee", hVotosQtd: "Votes per voter:", btnAddCand: "Add Candidates",
        hCandName: "Candidate name:", pCandName: "Full name", hCandFoto: "Candidate photo:", btnToList: "Add", btnSaveCargo: "Save Position", btnStartVote: "START VOTING 🗳️",
        btnConfirmVote: "CONFIRM VOTE", btnEndElection: "END ELECTION", tResults: "Results", btnDownload: "Download PDF 📄", btnFinish: "Finish and Exit",
        tFeedback: "Suggestions or Requests", pFeedback: "Your suggestion...", btnSendFeedback: "Send Suggestion",
        msgSelect: "Select a candidate.", msgVoteOk: "Vote recorded!", msgTitleErr: "Enter a name!", msgCargoErr: "Enter a position!", msgFeedOk: "Suggestion sent!"
    },
    es: {
        tLogin: "Acceso al Sistema", hEmail: "Email para créditos:", pEmail: "Su Gmail...", btnVerifyEmail: "Entrar", pInfo: "3 elecciones gratuitas.",
        tLimit: "Créditos Agotados", tPayOption: "Elección Individual", tPayOption20: "Paquete 20", btnPay: "Pagar R$ 30.00", btnPay20: "Pagar R$ 500.00", hCoupon: "¿Cupón?", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Volver",
        tConfirm: "Verifique Email", hCode: "Código enviado:", pCode: "Código", btnConfirm: "Confirmar",
        tGeneral: "Configuración", hElectionName: "Nombre de elección:", pElectionName: "Ej: Condominio Orion", btnNextStep: "Siguiente",
        tCargo: "Cargo", hCargoName: "Nombre del cargo:", pCargoName: "Ej: Síndico", hVotosQtd: "Votos por elector:", btnAddCand: "Agregar Candidatos",
        hCandName: "Nombre:", pCandName: "Nombre completo", hCandFoto: "Foto:", btnToList: "Agregar", btnSaveCargo: "Guardar Cargo", btnStartVote: "VOTAR 🗳️",
        btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "FINALIZAR", tResults: "Resultado", btnDownload: "Descargar PDF 📄", btnFinish: "Finalizar",
        tFeedback: "Sugerencias o Pedidos", pFeedback: "Su sugerencia...", btnSendFeedback: "Enviar",
        msgSelect: "Seleccione un candidato.", msgVoteOk: "¡Votado!", msgTitleErr: "Ponga un nombre.", msgCargoErr: "Ponga un cargo.", msgFeedOk: "¡Enviado!"
    }
};

// --- FUNÇÕES DE NAVEGAÇÃO E IDIOMA ---
function setLang(l) {
    lang = l;
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (i18n[l][key]) {
            if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.placeholder = i18n[l][key];
            else el.innerText = i18n[l][key];
        }
    });
}

function irPara(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    window.scrollTo(0,0);
}

// --- LÓGICA DE ACESSO E BACKEND ---
async function checkEmailBalance() {
    const val = document.getElementById("userEmail").value.trim().toUpperCase();
    if (val === _MK) { userEmail = "admin@total.com"; irPara('setupGeral'); return; }
    
    userEmail = val.toLowerCase();
    if(!userEmail.includes("@")) return alert("E-mail inválido");

    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    btn.innerText = "...";
    btn.disabled = true;

    try {
        const res = await fetch(`${BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`);
        const data = await res.json();

        if (data.saldo <= 0) {
            irPara('paymentScreen');
        } else {
            codigoEmail = data.codigo;
            await emailjs.send("service_oqfbzrm", "template_t3aio8f", { 
                to_email: userEmail, 
                validation_code: codigoEmail 
            });
            alert("Código enviado!");
            irPara('verify');
        }
    } catch (e) {
        // Fallback Local se o Worker falhar
        let history = JSON.parse(localStorage.getItem('urna_data') || "{}");
        if ((history[userEmail] || 0) >= 3) {
            irPara('paymentScreen');
        } else {
            irPara('setupGeral');
        }
    } finally {
        btn.innerText = "Entrar";
        btn.disabled = false;
    }
}

function validar() {
    const code = document.getElementById("inCode").value;
    if(code === codigoEmail.toString()) irPara('setupGeral');
    else alert("Erro: Código incorreto.");
}

function aplicarCupom() {
    const cupom = document.getElementById("inputCupom").value.trim().toUpperCase();
    if (cupom === _MK || cupom === _CK) {
        alert("Cupom Validado!");
        irPara('setupGeral');
    } else alert("Inválido.");
}

// --- CONFIGURAÇÃO DA ELEIÇÃO ---
function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if(!tituloEleicaoGlobal) return alert(i18n[lang].msgTitleErr);
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if(!nome) return alert(i18n[lang].msgCargoErr);
    cargoTemp = { nome, limite: parseInt(document.getElementById("qtdVotos").value), candidatos: [] };
    document.getElementById("tituloCargoAtual").innerText = (lang === 'pt' ? "Candidatos: " : lang === 'en' ? "Candidates: " : "Candidatos: ") + nome;
    irPara('setupCandidatos');
}

document.getElementById('fotoCand')?.addEventListener('change', (e) => {
    const reader = new FileReader();
    reader.onload = (ev) => fotoBase64 = ev.target.result;
    if(e.target.files[0]) reader.readAsDataURL(e.target.files[0]);
});

function addCandidato() {
    const nome = document.getElementById("nomeCand").value;
    if(!nome) return;
    cargoTemp.candidatos.push({ nome, foto: fotoBase64, votos: 0 });
    document.getElementById("listaTemp").innerHTML += `<div>• ${nome}</div>`;
    document.getElementById("nomeCand").value = "";
    fotoBase64 = "";
}

function finalizarCargo() {
    eleicaoData.push(cargoTemp);
    document.getElementById("nomeCargo").value = "";
    document.getElementById("listaTemp").innerHTML = "";
    irPara('setupCargo');
}

// --- URNA E VOTAÇÃO ---
function iniciarUrna() {
    if(cargoTemp && !eleicaoData.includes(cargoTemp)) eleicaoData.push(cargoTemp);
    if(eleicaoData.length === 0) return;
    indiceCargoAtual = 0;
    carregarCargoNaUrna();
    irPara('urnaVisual');
}

function carregarCargoNaUrna() {
    const cargo = eleicaoData[indiceCargoAtual];
    document.getElementById("votoCargoTitulo").innerText = cargo.nome;
    const grid = document.getElementById("gridVotacao");
    grid.innerHTML = "";
    votosSelecionados = [];

    cargo.candidatos.forEach((cand, i) => {
        const card = document.createElement("div");
        card.className = "card-candidato";
        card.innerHTML = `<img src="${cand.foto || ''}" class="foto-cand"><br><strong>${cand.nome}</strong>`;
        card.onclick = () => {
            if(votosSelecionados.includes(i)) {
                votosSelecionados = votosSelecionados.filter(v => v !== i);
                card.classList.remove("selected");
            } else if(votosSelecionados.length < cargo.limite) {
                votosSelecionados.push(i);
                card.classList.add("selected");
            }
        };
        grid.appendChild(card);
    });
}

function confirmarVotoVisual() {
    if(votosSelecionados.length === 0) return alert(i18n[lang].msgSelect);
    votosSelecionados.forEach(idx => eleicaoData[indiceCargoAtual].candidatos[idx].votos++);
    indiceCargoAtual++;
    if(indiceCargoAtual < eleicaoData.length) carregarCargoNaUrna();
    else { alert(i18n[lang].msgVoteOk); indiceCargoAtual = 0; carregarCargoNaUrna(); }
}

// --- FINALIZAÇÃO E PDF ---
async function exibirResultados() {
    // Avisar o Worker para descontar o saldo
    try { await fetch(`${BACKEND_URL}/?email=${userEmail}`, { method: 'POST' }); } catch(e){}

    const agora = new Date();
    document.getElementById("pdfTituloEleicao").innerText = tituloEleicaoGlobal;
    document.getElementById("pdfDataHora").innerText = agora.toLocaleString();
    const container = document.getElementById("containerResultados");
    container.innerHTML = "";

    eleicaoData.forEach(cargo => {
        let rank = [...cargo.candidatos].sort((a,b) => b.votos - a.votos);
        let html = `<div><h3 style="border-bottom: 2px solid #1abc9c; padding-bottom: 5px; margin-top: 25px;">${cargo.nome}</h3>`;
        rank.forEach((c, i) => html += `<p style="margin: 10px 0; border-bottom: 1px solid #eee; padding-bottom: 5px;"><strong>${i+1}º ${c.nome}</strong> — ${c.votos} votos</p>`);
        container.innerHTML += html + `</div>`;
    });
    irPara('resultadosScreen');
}

function gerarPDF() {
    const element = document.getElementById('areaImpressao');
    const opt = { margin: 15, filename: `Relatorio_${tituloEleicaoGlobal}.pdf`, image: { type: 'jpeg', quality: 0.98 }, html2canvas: { scale: 2, useCORS: true }, jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' } };
    html2pdf().set(opt).from(element).save();
}

function enviarSugestao() {
    const texto = document.getElementById("textoFeedback").value;
    if(!texto) return;
    emailjs.send("service_oqfbzrm", "template_t3aio8f", { to_email: "paulosmb1972@gmail.com", validation_code: "SUGESTÃO: " + texto })
    .then(() => { alert(i18n[lang].msgFeedOk); document.getElementById("textoFeedback").value = ""; });
}

function registrarFimEleicao() {
    location.reload();
}

// Impedir F12 e Clique Direito
document.onkeydown = (e) => { if(e.keyCode == 123 || (e.ctrlKey && e.shiftKey && e.keyCode == 73) || (e.ctrlKey && e.keyCode == 85)) return false; };
