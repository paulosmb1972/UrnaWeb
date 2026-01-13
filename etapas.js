// 1. Definimos os candidatos
let etapas = [
    {
        titulo: 'VEREADOR',
        numeros: 5,
        candidatos: [
            {
                numero: '38111',
                nome: 'CANDIDATO TESTE',
                partido: 'ABC',
                fotos: [{url: 'https://via.placeholder.com/150', legenda: 'Vereador'}]
            }
        ]
    }
];

// 2. Comando para trocar o nome "votafacil-pro" por "UrnaWeb" na tela
window.onload = function() {
    // Tenta trocar qualquer texto que fale do outro sistema
    document.body.innerHTML = document.body.innerHTML.replace(/votafacil-pro/g, 'UrnaWeb');
    
    // 3. COMANDO DE INICIALIZAÇÃO (O que faz o sistema sair do 'parado')
    if (typeof comecarEtapa === 'function') {
        comecarEtapa();
    } else if (typeof init === 'function') {
        init();
    }
};
