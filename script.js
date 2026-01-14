const CONFIG = {
    EMAIL_JS_PUBLIC_KEY: "_PKL4Oj92o48KurSF",
    EMAIL_JS_SERVICE: "service_oqfbzrm",
    EMAIL_JS_TEMPLATE: "template_t3aio8f",
    BACKEND_URL: "https://urnaweb-backend.paulosmb1972.workers.dev",
    CUPOM_MESTRE: "MAIS3GRATIS"
};

emailjs.init(CONFIG.EMAIL_JS_PUBLIC_KEY);

let userEmail = "";

async function checkEmailBalance() {
    const btn = document.querySelector('button[data-i18n="btnVerifyEmail"]');
    userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    if(!userEmail.includes("@")) return alert("E-mail inválido");

    btn.innerText = "Verificando...";
    btn.disabled = true;

    try {
        // 1. Consulta o Worker
        const res = await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`);
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        // 2. Controle de Saldo (3 Grátis)
        if (data.saldo === 0) {
            alert("Limite de 3 eleições atingido para: " + userEmail);
            irPara('paymentScreen');
            return;
        }

        // 3. Envio do E-mail (Código de Verificação)
        const emailStatus = await emailjs.send(CONFIG.EMAIL_JS_SERVICE, CONFIG.EMAIL_JS_TEMPLATE, {
            to_email: userEmail,
            validation_code: data.codigo
        });

        if (emailStatus.status !== 200) throw new Error("Falha no serviço de e-mail.");

        // 4. Validação do Código
        const inputCodigo = prompt("CÓDIGO ENVIADO! Verifique seu e-mail e digite aqui:");
        if (inputCodigo && inputCodigo.trim() === data.codigo.toString()) {
            alert("Bem-vindo! Esta é sua eleição nº " + (data.usado + 1));
            irPara('setupGeral');
        } else {
            alert("Código inválido.");
        }

    } catch (e) {
        console.error(e);
        alert("Erro no sistema: " + e.message + ". Verifique o Binding do KV no Cloudflare.");
    } finally {
        btn.innerText = "Entrar";
        btn.disabled = false;
    }
}

// Chame esta função SEMPRE que a eleição for encerrada
async function registrarUsoNoBanco() {
    try {
        await fetch(`${CONFIG.BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`, { method: 'POST' });
    } catch (e) { console.log("Erro ao salvar uso."); }
}

// Atualize sua função de encerrar eleição para incluir a linha abaixo:
function exibirResultados() {
    registrarUsoNoBanco(); // <--- ESSA LINHA FAZ O CONTROLE DO EMAIL FUNCIONAR
    // ... resto do seu código de resultados ...
}

function irPara(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(id).classList.add('active');
}
