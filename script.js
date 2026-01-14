// CONFIGURAÇÕES DE API E CHAVES DO USUÁRIO
const CONFIG = {
    EMAIL_JS_PUBLIC_KEY: "_PKL4Oj92o48KurSF",
    EMAIL_JS_SERVICE: "service_oqfbzrm",
    EMAIL_JS_TEMPLATE: "template_t3aio8f",
    BACKEND_URL: "https://urnaweb-backend.paulosmb1972.workers.dev/",
    CUPOM_MESTRE: "MAIS3GRATIS",
    PIX_ID: "c1141701-199d-4487-b0ec-e95a7a3f3915"
};

// Inicialização EmailJS
emailjs.init(CONFIG.EMAIL_JS_PUBLIC_KEY);

let lang = 'pt';
let userEmail = "";
let eleicaoData = [];
let cargoTemp = null;
let fotoBase64 = "";
let votosSelecionados = [];
let indiceCargoAtual = 0;
let tituloEleicaoGlobal = "";

const i18n = {
    pt: { tLogin: "Acesso ao Sistema", pEmail: "Seu Gmail...", btnVerifyEmail: "Entrar", tLimit: "Créditos Esgotados", pCoupon: "Código do Cupom", btnCoupon: "Validar", btnBack: "Voltar", tGeneral: "Início da Eleição", pElectionName: "Nome da Eleição", btnNextStep: "Próximo", tCargo: "Configurar Cargo", pCargoName: "Ex: Síndico", btnAddCand: "Candidatos", pCandName: "Nome Completo", btnToList: "Adicionar", btnSaveCargo: "Salvar Cargo", btnStartVote: "INICIAR VOTAÇÃO 🗳️", btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "ENCERRAR ELEIÇÃO", tResults: "Resultado", btnDownload: "Baixar PDF 📄", tFeedback: "Sugestões ou Pedidos", btnSendFeedback: "Enviar", btnFinish: "Finalizar e Sair" },
    en: { tLogin: "System Access", pEmail: "Your Gmail...", btnVerifyEmail: "Login", tLimit: "Credits Exhausted", pCoupon: "Coupon Code", btnCoupon: "Validate", btnBack: "Back", tGeneral: "Election Setup", pElectionName: "Election Name", btnNextStep: "Next", tCargo: "Position Setup", pCargoName: "e.g. Trustee", btnAddCand: "Add Candidates", pCandName: "Full Name", btnToList: "Add", btnSaveCargo: "Save Position", btnStartVote: "START VOTING 🗳️", btnConfirmVote: "CONFIRM VOTE", btnEndElection: "END ELECTION", tResults: "Results", btnDownload: "Download PDF 📄", tFeedback: "Feedback/Requests", btnSendFeedback: "Send", btnFinish: "Exit" },
    es: { tLogin: "Acceso al Sistema", pEmail: "Su Gmail...", btnVerifyEmail: "Entrar", tLimit: "Créditos Agotados", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Volver", tGeneral: "Configuración", pElectionName: "Nombre de Elección", btnNextStep: "Siguiente", tCargo: "Cargo", pCargoName: "Ej: Síndico", btnAddCand: "Candidatos", pCandName: "Nombre Completo", btnToList: "Agregar", btnSaveCargo: "Guardar Cargo", btnStartVote: "VOTAR 🗳️", btnConfirmVote: "CONFIRMAR VOTO", btnEndElection: "FINALIZAR", tResults: "Resultado", btnDownload: "Descargar PDF 📄", tFeedback: "Sugerencias", btnSendFeedback: "Enviar", btnFinish: "Salir" }
};

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

// Ajuste na chamada da URL dentro da função
async function checkEmailBalance() {
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    if(!userEmail.includes("@") || userEmail.length < 5) {
        alert(lang === 'pt' ? "Por favor, insira um e-mail válido." : "Please enter a valid email.");
        return;
    }

    const originalText = btn.innerText;
    btn.innerText = "...";
    btn.disabled = true;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        // CORREÇÃO AQUI: De CONFIG.BACK para CONFIG.BACKEND_URL
        const res = await fetch(`${CONFIG.BACKEND_URL}?email=${userEmail}`, {
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        const data = await res.json();

        if(data && data.saldo > 0) {
            irPara('setupGeral');
        } else {
            irPara('paymentScreen');
        }
    } catch(e) { 
        console.error("Erro na validação:", e);
        // Fallback para não travar o usuário enquanto o Worker propaga
        alert("Modo de segurança ativado.");
        irPara('setupGeral'); 
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
}

function aplicarCupom() {
    const cupom = document.getElementById("inputCupom").value.trim().toUpperCase();
    if (cupom === CONFIG.CUPOM_MESTRE) {
        alert("Cupom validado com sucesso!");
        irPara('setupGeral');
    } else {
        alert("Cupom inválido.");
    }
}

// Configuração da Eleição
function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if(!tituloEleicaoGlobal) return alert("Dê um nome à eleição");
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if(!nome) return alert("Defina o cargo");
    cargoTemp = { nome, limite: parseInt(document.getElementById("qtdVotos").value), candidatos: [] };
    document.getElementById("tituloCargoAtual").innerText = nome;
    irPara('setupCandidatos');
}

// Tratamento de Imagem
document.getElementById('fotoCand')?.addEventListener('change', (e) => {
    const reader = new FileReader();
    reader.onload = (ev) => fotoBase64 = ev.target.result;
    reader.readAsDataURL(e.target.files[0]);
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
    if(votosSelecionados.length === 0) return alert("Selecione um candidato");
    votosSelecionados.forEach(idx => eleicaoData[indiceCargoAtual].candidatos[idx].votos++);
    indiceCargoAtual++;
    
    if(indiceCargoAtual < eleicaoData.length) {
        carregarCargoNaUrna();
    } else {
        alert("Voto Confirmado!");
        indiceCargoAtual = 0;
        carregarCargoNaUrna();
    }
}

// Resultados e PDF
function exibirResultados() {
    const agora = new Date();
    document.getElementById("pdfTituloEleicao").innerText = tituloEleicaoGlobal;
    document.getElementById("pdfDataHora").innerText = agora.toLocaleString();
    const container = document.getElementById("containerResultados");
    container.innerHTML = "";

    eleicaoData.forEach(cargo => {
        let html = `<h3 style="border-bottom: 2px solid #1abc9c; margin-top:20px;">${cargo.nome}</h3>`;
        cargo.candidatos.sort((a,b) => b.votos - a.votos).forEach((c, i) => {
            html += `<p><strong>${i+1}º ${c.nome}</strong>: ${c.votos} votos</p>`;
        });
        container.innerHTML += html;
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

// Feedback via EmailJS
function enviarSugestao() {
    const texto = document.getElementById("textoFeedback").value;
    if(!texto) return;

    emailjs.send(CONFIG.EMAIL_JS_SERVICE, CONFIG.EMAIL_JS_TEMPLATE, {
        to_email: "paulosmb1972@gmail.com",
        validation_code: "SUGESTÃO URNAWEB: " + texto
    }).then(() => {
        alert("Sugestão enviada! Obrigado.");
        document.getElementById("textoFeedback").value = "";
    });
}
