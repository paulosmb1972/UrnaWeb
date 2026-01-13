// Definindo os dados da UrnaWeb
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

// Comandos para trocar o nome e iniciar o sistema
window.onload = function() {
    // Muda o título na aba do navegador
    document.title = "UrnaWeb";
    
    // Tenta forçar o início do sistema se a função existir
    if (typeof comecarEtapa === 'function') {
        comecarEtapa();
    }
};
