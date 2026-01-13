let etapaAtual = 0;
let numero = '';
let votoBranco = false;

function comecarEtapa() {
    let etapa = etapas[etapaAtual];
    let numeroHtml = '';
    numero = '';
    votoBranco = false;

    for(let i=0; i<etapa.numeros; i++) {
        numeroHtml += i === 0 ? '<div class="numero pisca"></div>' : '<div class="numero"></div>';
    }

    // Ajustes de exibição inicial
    document.querySelector('.d-1-2 span').style.display = 'none';
    document.querySelector('.d-1-3 span').innerHTML = etapa.titulo;
    document.querySelector('.d-1-info').innerHTML = ''; // Limpa info anterior
    document.querySelector('.d-1-4').innerHTML = numeroHtml;
    document.querySelector('.d-1-right').innerHTML = '';
    document.querySelector('.d-2').style.display = 'none';
}

function atualizarInterface() {
    let etapa = etapas[etapaAtual];
    let candidato = etapa.candidatos.filter((item) => item.numero === numero)[0];

    if(candidato) {
        document.querySelector('.d-1-2 span').style.display = 'block';
        // AJUSTE: Usamos a div d-1-info para não bagunçar o layout
        document.querySelector('.d-1-info').innerHTML = `Nome: ${candidato.nome}<br>Partido: ${candidato.partido}`;
        
        let fotosHtml = '';
        for(let i in candidato.fotos) {
            // AJUSTE: Verificamos se a foto é pequena (vice) ou grande
            if(candidato.fotos[i].small) {
                fotosHtml += `<div class="d-1-image small"><img src="${candidato.fotos[i].url}" alt="" />${candidato.fotos[i].legenda}</div>`;
            } else {
                fotosHtml += `<div class="d-1-image"><img src="${candidato.fotos[i].url}" alt="" />${candidato.fotos[i].legenda}</div>`;
            }
        }
        document.querySelector('.d-1-right').innerHTML = fotosHtml;
        document.querySelector('.d-2').style.display = 'block';
    } else {
        document.querySelector('.d-1-2 span').style.display = 'block';
        document.querySelector('.d-1-info').innerHTML = '<div class="aviso--grande pisca">VOTO NULO</div>';
        document.querySelector('.d-2').style.display = 'block';
    }
}

function clicou(n) {
    let elNumero = document.querySelector('.numero.pisca');
    if(elNumero !== null) {
        elNumero.innerHTML = n;
        numero = `${numero}${n}`;
        elNumero.classList.remove('pisca');
        if(elNumero.nextElementSibling !== null) {
            elNumero.nextElementSibling.classList.add('pisca');
        } else {
            atualizarInterface();
        }
    }
}

function branco() {
    if(numero === '') {
        votoBranco = true;
        document.querySelector('.d-1-2 span').style.display = 'block';
        document.querySelector('.d-1-4').innerHTML = '';
        document.querySelector('.d-1-info').innerHTML = '<div class="aviso--grande pisca">VOTO EM BRANCO</div>';
        document.querySelector('.d-2').style.display = 'block';
    }
}

function corrige() { comecarEtapa(); }

function confirma() {
    let etapa = etapas[etapaAtual];
    let votoConfirmado = false;

    if(votoBranco === true) {
        votoConfirmado = true;
    } else if(numero.length === etapa.numeros) {
        votoConfirmado = true;
    }

    if(votoConfirmado) {
        etapaAtual++;
        if(etapas[etapaAtual] !== undefined) {
            comecarEtapa();
        } else {
            document.querySelector('.tela').innerHTML = '<div class="aviso--gigante">FIM</div>';
        }
    }
}

// Inicializa a urna
comecarEtapa();
