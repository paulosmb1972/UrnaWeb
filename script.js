// Configurações Iniciais
emailjs.init("_PKL4Oj92o48KurSF");
const _CK = "MAIS3GRATIS"; // Exemplo de cupom

const i18n = {
    pt: { tLogin: "Acesso", pEmail: "Seu Gmail...", btnVerifyEmail: "Entrar", tLimit: "Créditos Esgotados", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Voltar", tGeneral: "Início", pElectionName: "Nome da Eleição", btnNextStep: "Próximo", tCargo: "Cargo", pCargoName: "Nome da Função", btnAddCand: "Candidatos", pCandName: "Nome Completo", btnToList: "Adicionar", btnSaveCargo: "Salvar Cargo", btnStartVote: "VOTAR", btnConfirmVote: "CONFIRMAR", btnEndElection: "ENCERRAR", tResults: "Resultado", btnDownload: "Baixar PDF", tFeedback: "Sugestões", btnSendFeedback: "Enviar", btnFinish: "Sair" },
    en: { tLogin: "Access", pEmail: "Your Gmail...", btnVerifyEmail: "Login", tLimit: "No Credits", pCoupon: "Code", btnCoupon: "Validate", btnBack: "Back", tGeneral: "Setup", pElectionName: "Election Name", btnNextStep: "Next", tCargo: "Position", pCargoName: "Function Name", btnAddCand: "Candidates", pCandName: "Full Name", btnToList: "Add", btnSaveCargo: "Save Position", btnStartVote: "START", btnConfirmVote: "CONFIRM", btnEndElection: "END", tResults: "Results", btnDownload: "Get PDF", tFeedback: "Feedback", btnSendFeedback: "Send", btnFinish: "Exit" },
    es: { tLogin: "Acceso", pEmail: "Su Gmail...", btnVerifyEmail: "Entrar", tLimit: "Sin Créditos", pCoupon: "Código", btnCoupon: "Validar", btnBack: "Volver", tGeneral: "Inicio", pElectionName: "Nombre Elección", btnNextStep: "Siguiente", tCargo: "Cargo", pCargoName: "Nombre Cargo", btnAddCand: "Candidatos", pCandName: "Nombre Completo", btnToList: "Agregar", btnSaveCargo: "Guardar Cargo", btnStartVote: "VOTAR", btnConfirmVote: "CONFIRMAR", btnEndElection: "FINALIZAR", tResults: "Resultado", btnDownload: "Descargar PDF", tFeedback: "Sugerencias", btnSendFeedback: "Enviar", btnFinish: "Salir" }
};

let lang = 'pt';
let eleicaoData = [];
let cargoTemp = null;
let fotoBase64 = "";
let votosSelecionados = [];
let indiceCargoAtual = 0;

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
}

function aplicarCupom() {
    const cupom = document.getElementById("inputCupom").value.trim().toUpperCase();
    if (cupom === _CK) {
        alert("Cupom Válido!");
        irPara('setupGeral');
    } else {
        alert("Cupom Inválido.");
    }
}

// Lógica de PDF
function gerarPDF() {
    const element = document.getElementById('areaImpressao');
    const opt = {
        margin: 10,
        filename: 'Resultado_Eleicao.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };
    html2pdf().set(opt).from(element).save();
}

// ... Restante das funções (checkEmailBalance, addCandidato, etc) seguem a mesma lógica anterior ...
