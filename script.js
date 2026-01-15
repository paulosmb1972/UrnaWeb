// CONFIGURAÇÕES INICIAIS
emailjs.init("_PKL4Oj92o48KurSF");

const CONFIG = {
    BACKEND_URL: "https://urnaweb-backend.paulosmb1972.workers.dev",
    EMAIL_SERVICE: "service_oqfbzrm",
    EMAIL_TEMPLATE: "template_t3aio8f",
    CUPOM_MESTRE: "MAIS3GRATIS",
    ADMIN_KEY: "ORION001"
};

let lang = 'pt';
let userEmail = "";
let codigoVerificacao = "";
let eleicaoData = [];
let cargoTemp = null;
let fotoBase64 = "";
let votosSelecionados = [];
let indiceCargoAtual = 0;
let tituloEleicaoGlobal = "";

// DICIONÁRIO MULTI-IDIOMA
const i18n = {
    pt: {
        tLogin: "Acesso ao Sistema", pEmail: "Seu Gmail...", btnVerifyEmail: "Entrar",
        tLimit: "Créditos Esgotados", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Voltar",
        tConfirm: "Verifique seu E-mail", pCode: "Código", btnConfirm: "Confirmar",
        tGeneral: "Início da Eleição", pElectionName: "Ex: Condomínio Orion", btnNextStep: "Próximo",
        tCargo: "Configurar Cargo", pCargoName: "Ex: Síndico", btnAddCand: "Candidatos",
        pCandName: "Nome completo", btnToList: "Adicionar", btnSaveCargo: "Salvar Cargo",
        btnStartVote: "INICIAR VOTAÇÃO 🗳️", btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "ENCERRAR ELEIÇÃO",
        tResults: "Resultado", btnDownload: "Baixar PDF 📄", btnFinish: "Finalizar e Sair",
        tFeedback: "Sugestões ou Pedidos", btnSendFeedback: "Enviar",
        msgSelect: "Selecione um candidato.", msgVoteOk: "Voto computado!", msgErr: "Erro técnico.", msgFeedOk: "Enviado!"
    },
    en: {
        tLogin: "System Access", pEmail: "Your Gmail...", btnVerifyEmail: "Enter",
        tLimit: "Credits Exhausted", pCoupon: "Code", btnCoupon: "Validate", btnBack: "Back",
        tConfirm: "Check Email", pCode: "Code", btnConfirm: "Confirm",
        tGeneral: "Election Setup", pElectionName: "e.g. Orion Condo", btnNextStep: "Next",
        tCargo: "Position Setup", pCargoName: "e.g. Trustee", btnAddCand: "Add Candidates",
        pCandName: "Full name", btnToList: "Add", btnSaveCargo: "Save Position",
        btnStartVote: "START VOTING 🗳️", btnConfirmVote: "CONFIRM VOTE", btnEndElection: "END ELECTION",
        tResults: "Results", btnDownload: "Download PDF 📄", btnFinish: "Finish and Exit",
        tFeedback: "Suggestions", btnSendFeedback: "Send",
        msgSelect: "Select a candidate.", msgVoteOk: "Vote recorded!", msgErr: "Technical error.", msgFeedOk: "Sent!"
    },
    es: {
        tLogin: "Acceso al Sistema", pEmail: "Su Gmail...", btnVerifyEmail: "Entrar",
        tLimit: "Créditos Agotados", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Volver",
        tConfirm: "Verifique Email", pCode: "Código", btnConfirm: "Confirmar",
        tGeneral: "Configuración", pElectionName: "Ej: Condominio Orion", btnNextStep: "Siguiente",
        tCargo: "Cargo", pCargoName: "Ej: Síndico", btnAddCand: "Agregar Candidatos",
        pCandName: "Nombre completo", btnToList: "Agregar", btnSaveCargo: "Guardar Cargo",
        btnStartVote: "VOTAR 🗳️", btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "FINALIZAR",
        tResults: "Resultado", btnDownload: "Descargar PDF 📄", btnFinish: "Finalizar",
        tFeedback: "Sugerencias", btnSendFeedback: "Enviar",
        msgSelect: "Seleccione un candidato.", msgVoteOk: "¡Votado!", msgErr: "Error técnico.", msgFeedOk: "¡Enviado!"
    }
};

// NAVEGAÇÃO
function irPara(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    window.scrollTo(0, 0);
}

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

// LOGIN E VERIFICAÇÃO DE SALDO
async function checkEmailBalance() {
    const emailInput = document.getElementById("userEmail").value.trim().toLowerCase();
    if (!emailInput.includes("@")) return alert("E-mail inválido");
    
    userEmail = emailInput;
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    btn.disabled = true;

    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`);
        const data = await response.json();

        if (data.saldo <= 0) {
            irPara('paymentScreen');
        } else {
            codigoVerificacao = data.codigo;
            await emailjs.send(CONFIG.EMAIL_SERVICE, CONFIG.EMAIL_TEMPLATE, {
                to_email: userEmail,
                validation_code: codigoVerificacao
            });
            alert("Código de verificação enviado!");
            irPara('verify');
        }
    } catch (e) {
        alert("Erro de conexão com o servidor.");
    } finally {
        btn.disabled = false;
    }
}

function validar() {
    const input = document.getElementById("inCode").value.trim();
    if (input === codigoVerificacao.toString() || input === CONFIG.ADMIN_KEY) {
        irPara('setupGeral');
    } else {
        alert("Código incorreto.");
    }
}

function aplicarCupom() {
    const cupom = document.getElementById("inputCupom").value.trim().toUpperCase();
    if (cupom === CONFIG.CUPOM_MESTRE) {
        alert("Cupom validado!");
        irPara('setupGeral');
    } else {
        alert("Cupom inválido.");
    }
}

// CONFIGURAÇÃO DA ELEIÇÃO
function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if (!tituloEleicaoGlobal) return alert(i18n[lang].msgErr);
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if (!nome) return alert(i18n[lang].msgErr);
    cargoTemp = { nome, limite: parseInt(document.getElementById("qtdVotos").value), candidatos: [] };
    document.getElementById("tituloCargoAtual").innerText = nome;
    irPara('setupCandidatos');
}

document.getElementById('fotoCand')?.addEventListener('change', (e) => {
    const reader = new FileReader();
    reader.onload = (ev) => fotoBase64 = ev.target.result;
    if (e.target.files[0]) reader.readAsDataURL(e.target.files[0]);
});

function addCandidato() {
    const nome = document.getElementById("nomeCand").value;
    if (!nome) return;
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

// URNA
function iniciarUrna() {
    if (cargoTemp && !eleicaoData.includes(cargoTemp)) eleicaoData.push(cargoTemp);
    if (eleicaoData.length === 0) return;
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
            if (votosSelecionados.includes(i)) {
                votosSelecionados = votosSelecionados.filter(v => v !== i);
                card.classList.remove("selected");
            } else if (votosSelecionados.length < cargo.limite) {
                votosSelecionados.push(i);
                card.classList.add("selected");
            }
        };
        grid.appendChild(card);
    });
}

function confirmarVotoVisual() {
    if (votosSelecionados.length === 0) return alert(i18n[lang].msgSelect);
    votosSelecionados.forEach(idx => eleicaoData[indiceCargoAtual].candidatos[idx].votos++);
    indiceCargoAtual++;
    if (indiceCargoAtual < eleicaoData.length) {
        carregarCargoNaUrna();
    } else {
        alert(i18n[lang].msgVoteOk);
        indiceCargoAtual = 0;
        carregarCargoNaUrna();
    }
}

// RESULTADOS E PDF
async function exibirResultados() {
    try {
        await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`, { method: 'POST' });
    } catch (e) { console.error("Erro ao registrar uso."); }

    const agora = new Date();
    document.getElementById("pdfTituloEleicao").innerText = tituloEleicaoGlobal;
    document.getElementById("pdfDataHora").innerText = agora.toLocaleString();
    const container = document.getElementById("containerResultados");
    container.innerHTML = "";

    eleicaoData.forEach(cargo => {
        let html = `<div><h3 style="border-bottom: 2px solid #1abc9c; padding-bottom: 5px; margin-top: 25px;">${cargo.nome}</h3>`;
        const rank = [...cargo.candidatos].sort((a, b) => b.votos - a.votos);
        rank.forEach((c, i) => {
            html += `<p style="margin: 10px 0; border-bottom: 1px solid #eee; padding-bottom: 5px;"><strong>${i + 1}º ${c.nome}</strong> — ${c.votos} votos</p>`;
        });
        container.innerHTML += html + `</div>`;
    });
    irPara('resultadosScreen');
}

function gerarPDF() {
    const element = document.getElementById('areaImpressao');
    const opt = { 
        margin: 15, 
        filename: `Relatorio_${tituloEleicaoGlobal}.pdf`, 
        html2canvas: { scale: 2 }, 
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' } 
    };
    html2pdf().set(opt).from(element).save();
}

function enviarSugestao() {
    const texto = document.getElementById("textoFeedback").value;
    if (!texto) return;
    emailjs.send(CONFIG.EMAIL_SERVICE, CONFIG.EMAIL_TEMPLATE, { 
        to_email: "paulosmb1972@gmail.com", 
        validation_code: "SUGESTÃO: " + texto 
    }).then(() => {
        alert(i18n[lang].msgFeedOk);
        document.getElementById("textoFeedback").value = "";
    });
}

function registrarFimEleicao() {
    location.reload();
}

// BLOQUEIOS DE SEGURANÇA
document.onkeydown = (e) => {
    if (e.keyCode == 123 || (e.ctrlKey && e.shiftKey && e.keyCode == 73) || (e.ctrlKey && e.keyCode == 85)) return false;
};
