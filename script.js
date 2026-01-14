// CONFIGURAÇÕES DE API
const CONFIG = {
    EMAIL_JS_PUBLIC_KEY: "_PKL4Oj92o48KurSF",
    EMAIL_JS_SERVICE: "service_oqfbzrm",
    EMAIL_JS_TEMPLATE: "template_t3aio8f",
    BACKEND_URL: "https://urnaweb-backend.paulosmb1972.workers.dev/",
    CUPOM_MESTRE: "MAIS3GRATIS"
};

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

// Funções de Interface
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

async function checkEmailBalance() {
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    if(!userEmail.includes("@")) return alert("E-mail inválido");

    btn.innerText = "Verificando...";
    btn.disabled = true;

    try {
        // 1. Chamada ao Worker
        const res = await fetch(`${CONFIG.BACKEND_URL}?email=${userEmail}`);
        if (!res.ok) throw new Error("Erro na resposta do servidor");
        
        const data = await res.json();
        console.log("Dados recebidos do Worker:", data); // Para você ver no F12 do navegador

        // 2. Se não tiver saldo, para aqui
        if (data.saldo <= 0) {
            irPara('paymentScreen');
            return;
        }

        // 3. Tenta enviar o e-mail (O sistema SÓ avança se o e-mail for enviado)
        console.log("Tentando enviar e-mail para:", userEmail);
        const emailRes = await emailjs.send(CONFIG.EMAIL_JS_SERVICE, CONFIG.EMAIL_JS_TEMPLATE, {
            to_email: userEmail,
            validation_code: data.codigo 
        });

        if(emailRes.status !== 200) throw new Error("EmailJS falhou");

        // 4. Pergunta o código
        const inputCodigo = prompt("CÓDIGO ENVIADO! Verifique sua caixa de entrada ou spam e digite o código de 6 dígitos:");
        
        if (inputCodigo === data.codigo) {
            alert("Acesso Autorizado!");
            irPara('setupGeral');
        } else {
            alert("Código incorreto. Acesso negado.");
        }

    } catch (e) {
        console.error("ERRO CRÍTICO:", e);
        alert("Falha técnica: Verifique se o Worker está configurado e se o EmailJS tem saldo.");
    } finally {
        btn.innerText = "Entrar";
        btn.disabled = false;
    }
}
// LÓGICA DE INCREMENTO DE USO (A 4ª Eleição trava aqui)
async function registrarFimDeEleicao() {
    try {
        await fetch(`${CONFIG.BACKEND_URL}?email=${userEmail}`, { method: 'POST' });
    } catch (e) { console.error("Erro ao computar uso."); }
}

function exibirResultados() {
    registrarFimDeEleicao(); // Avisa o banco que essa eleição foi concluída
    
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

// --- Restante das funções de configuração (Candidatos, Urna, PDF) ---
function aplicarCupom() {
    if (document.getElementById("inputCupom").value.trim().toUpperCase() === CONFIG.CUPOM_MESTRE) {
        alert("Cupom validado!");
        irPara('setupGeral');
    } else alert("Inválido.");
}

function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if(!tituloEleicaoGlobal) return alert("Dê um nome");
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if(!nome) return alert("Defina o cargo");
    cargoTemp = { nome, limite: parseInt(document.getElementById("qtdVotos").value), candidatos: [] };
    document.getElementById("tituloCargoAtual").innerText = nome;
    irPara('setupCandidatos');
}

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
    if(indiceCargoAtual < eleicaoData.length) carregarCargoNaUrna();
    else { alert("Voto Confirmado!"); indiceCargoAtual = 0; carregarCargoNaUrna(); }
}

function gerarPDF() {
    const element = document.getElementById('areaImpressao');
    html2pdf().set({ margin: 15, filename: 'Relatorio.pdf', html2canvas: { scale: 2 }, jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' } }).from(element).save();
}

function enviarSugestao() {
    const texto = document.getElementById("textoFeedback").value;
    if(!texto) return;
    emailjs.send(CONFIG.EMAIL_JS_SERVICE, CONFIG.EMAIL_JS_TEMPLATE, { to_email: "paulosmb1972@gmail.com", validation_code: "SUGESTÃO: " + texto })
    .then(() => { alert("Sugestão enviada!"); document.getElementById("textoFeedback").value = ""; });
}
