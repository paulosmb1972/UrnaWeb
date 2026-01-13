let etapas = [
    {
        titulo: 'VEREADOR',
        numeros: 5,
        candidatos: [
            {
                numero: '38111',
                nome: 'CANDIDATO TESTE',
                partido: 'PARTIDO DA URNA',
                fotos: [{url: 'https://via.placeholder.com/150', legenda: 'Vereador'}]
            }
        ]
    }
];

// Isso força o sistema a iniciar e ignora o nome do sistema antigo
window.onload = () => {
    if (typeof comecarEtapa === 'function') {
        comecarEtapa();
    }
};
