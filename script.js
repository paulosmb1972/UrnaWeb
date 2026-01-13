// Inicialização
emailjs.init("_PKL4Oj92o48KurSF");

let eleicaoData = [];
let cargoTemp = null;
let fotoBase64 = "";
let votosSelecionados = [];
let indiceCargoAtual = 0;
let tituloEleicaoGlobal = "";

function irPara(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}

function checkEmailBalance() {
    // Simplificado para teste, já que o original dependia de servidor
    irPara('setupGeral');
}

function irParaCargo() {
    tituloEleicaoGlobal = document.getElementById("tituloEleicaoInput").value;
    if(!tituloEleicaoGlobal) return alert("Digite o nome da eleição!");
    irPara('setupCargo');
}

function proximoPassoCandidatos() {
    const nome = document.getElementById("nomeCargo").value;
    if(!nome) return alert("Digite o nome do cargo!");
    cargoTemp = { nome, limite: parseInt(document.getElementById("qtdVotos").value), candidatos: [] };
    document.getElementById("tituloCargoAtual").innerText = "Candidatos para: " + nome;
    irPara('setupCandidatos');
}

// Converter imagem para Base64
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
    if(cargoTemp.candidatos.length === 0) return alert("Adicione ao menos um candidato!");
    eleicaoData.push(cargoTemp);
    document.getElementById("nomeCargo").value = "";
    document.getElementById("listaTemp").innerHTML = "";
    irPara('setupCargo');
}

function iniciarUrna() {
    if(cargoTemp && !eleicaoData.includes(cargoTemp)) eleicaoData.push(cargoTemp);
    if(eleicaoData.length === 0) return alert("Configure os cargos primeiro!");
    indiceCargoAtual = 0;
    carregarCargoNaUrna();
    irPara('urnaVisual');
}

function carregarCargoNaUrna() {
    const cargo = eleicaoData[indiceCargoAtual];
    document.getElementById("votoCargoTitulo").innerText = "Vote para: " + cargo.nome;
    const grid = document.getElementById("gridVotacao");
    grid.innerHTML = "";
    votosSelecionados = [];

    cargo.candidatos.forEach((cand, i) => {
        const card = document.createElement("div");
        card.className = "card-candidato";
        card.innerHTML = `<img src="${cand.foto || 'https://via.placeholder.com/150'}" class="foto-cand"><br><strong>${cand.nome}</strong>`;
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
    if(votosSelecionados.length === 0) return alert("Selecione um candidato!");
    votosSelecionados.forEach(idx => eleicaoData[indiceCargoAtual].candidatos[idx].votos++);
    
    indiceCargoAtual++;
    if(indiceCargoAtual < eleicaoData.length) {
        carregarCargoNaUrna();
    } else {
        alert("Todos os votos registrados!");
        indiceCargoAtual = 0; 
        carregarCargoNaUrna(); // Reinicia para o próximo eleitor
    }
}

function exibirResultados() {
    document.getElementById("pdfTituloEleicao").innerText = tituloEleicaoGlobal;
    const container = document.getElementById("containerResultados");
    container.innerHTML = "";

    eleicaoData.forEach(cargo => {
        let html = `<h3>${cargo.nome}</h3>`;
        cargo.candidatos.sort((a,b) => b.votos - a.votos).forEach(c => {
            html += `<p>${c.nome}: ${c.votos} votos</p>`;
        });
        container.innerHTML += html;
    });
    irPara('resultadosScreen');
}

function gerarPDF() {
    const element = document.getElementById('areaImpressao');
    html2pdf().from(element).save('resultado_eleicao.pdf');
}
