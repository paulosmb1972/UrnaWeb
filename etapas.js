window.config = {
    nomeSistema: "UrnaWeb",
    etapas: [
        {
            titulo: 'VEREADOR',
            numeros: 5,
            candidatos: [
                {
                    numero: '38111',
                    nome: 'CANDIDATO TESTE',
                    partido: 'PARTIDO TESTE',
                    fotos: [{url: 'https://via.placeholder.com/150', legenda: 'Vereador'}]
                }
            ]
        }
    ]
};

// Por garantia, se o script procurar por 'etapas' diretamente:
let etapas = window.config.etapas;
