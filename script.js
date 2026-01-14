// CONFIGURAÇÕES DE API E CHAVES DO USUÁRIO
const CONFIG = {
    EMAIL_JS_PUBLIC_KEY: "_PKL4Oj92o48KurSF",
    EMAIL_JS_SERVICE: "service_oqfbzrm",
    EMAIL_JS_TEMPLATE: "template_t3aio8f",
    // Backend sem barra final para evitar erro de concatenação
    BACKEND_URL: "https://urnaweb-backend.paulosmb1972.workers.dev", 
    CUPOM_MESTRE: "MAIS3GRATIS"
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

// --- NAVEGAÇÃO E IDIOMA ---
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

// --- LOGIN, SALDO E ENVIO DE CÓDIGO ---
async function checkEmailBalance() {
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    if(!userEmail.includes("@")) return alert("Por favor, insira um e-mail válido.");

    btn.innerText = "Aguarde...";
    btn.disabled = true;

    try {
        // Chamada ao Worker com tratamento de CORS e URL limpa
        const response = await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`, {
            method: 'GET',
            mode: 'cors'
        });

        if (!response.ok) throw new Error("Erro na comunicação com o servidor.");
        
        const data = await response.json();

        // 1. Verifica se tem saldo (usos < 3 ou pago)
        if (data.saldo <= 0) {
            alert("Limite de 3 eleições grátis atingido para este e-mail.");
            irPara('paymentScreen');
            return;
        }

        // 2. Envia o e-mail via EmailJS
        const emailStatus = await emailjs.send(CONFIG.EMAIL_JS_SERVICE, CONFIG.EMAIL_JS_TEMPLATE, {
            to_email: userEmail,
            validation_code: data.codigo
        });

        if (emailStatus.status !== 200) throw new Error("Falha ao enviar e-mail de verificação.");

        // 3. Validação do código por Prompt
        const inputCodigo = prompt("CÓDIGO ENVIADO! Verifique seu e-mail e digite o código de 6 dígitos:");
        
        if (inputCodigo && inputCodigo.trim() === data.codigo.toString()) {
            alert("Acesso autorizado!");
            irPara('setupGeral');
        } else {
            alert("Código incorreto ou cancelado.");
        }

    } catch (error) {
        console.error("Erro Crítico:", error);
        alert("Erro: " + error.message);
    } finally {
        btn.innerText = "Entrar";
        btn.disabled = false;
    }
}

// --- ATUALIZAÇÃO DO BANCO (CHAMADA POST) ---
async function registrarUsoNoBanco() {
    try {
        await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`, { 
            method: 'POST',
            mode: 'cors'
        });
        console.log("Uso registrado com sucesso.");
    } catch (e) {
        console.error("Não foi possível atualizar o saldo no banco.");
    }
}

// --- CONFIGURAÇÃO DA ELEIÇÃO ---
function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if(!tituloEleicaoGlobal) return alert("Dê um nome à eleição");
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if(!nome) return alert("Defina o cargo");
    cargoTemp = { 
        nome, 
        limite: parseInt(document.getElementById("qtdVotos").value) || 1, 
        candidatos: [] 
    };
    document.getElementById("tituloCargoAtual").innerText = nome;
    irPara('setupCandidatos');
}

// TRATAMENTO DE IMAGEM
document.getElementById('fotoCand')?.addEventListener('change', (e) => {
    const reader = new FileReader();
    reader.onload = (ev) => fotoBase64 = ev.target.result;
    if(e.target.files[0]) reader.readAsDataURL(e.target.files[0]);
});

function addCandidato() {
    const nome = document.getElementById("nomeCand").value;
    if(!nome) return alert("Digite o nome do candidato");
    cargoTemp.candidatos.push({ nome, foto: fotoBase64, votos: 0 });
    document.getElementById("listaTemp").innerHTML += `<div>• ${nome}</div>`;
    document.getElementById("nomeCand").value = "";
    document.getElementById("fotoCand").value = "";
    fotoBase64 = "";
}

function finalizarCargo() {
    if(cargoTemp.candidatos.length === 0) return alert("Adicione ao menos um candidato");
    eleicaoData.push(cargoTemp);
    document.getElementById("nomeCargo").value = "";
    document.getElementById("listaTemp").innerHTML = "";
    irPara('setupCargo');
}

// --- URNA E VOTAÇÃO ---
function iniciarUrna() {
    if(cargoTemp && !eleicaoData.includes(cargoTemp)) eleicaoData.push(cargoTemp);
    if(eleicaoData.length === 0) return alert("Configure ao menos um cargo");
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

    cargo
