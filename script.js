// CONFIGURAÇÕES DE API E CHAVES DO USUÁRIO
const CONFIG = {
    EMAIL_JS_PUBLIC_KEY: "_PKL4Oj92o48KurSF",
    EMAIL_JS_SERVICE: "service_oqfbzrm",
    EMAIL_JS_TEMPLATE: "template_t3aio8f",
    // Backend sem barra final para evitar erro de URL dupla
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

// --- NAVEGAÇÃO ---
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

// --- LOGIN E CONTROLE DE SALDO ---
async function checkEmailBalance() {
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    if(!userEmail.includes("@")) return alert("E-mail inválido");

    btn.innerText = "Conectando...";
    btn.disabled = true;

    try {
        // 1. Chamada ao Worker com tratamento de URL e CORS
        const url = `${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`;
        const res = await fetch(url, { method: 'GET', mode: 'cors' });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.error || "Erro
