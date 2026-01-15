// High-level logic extracted from the VM bytecode
async function checkEmailBalance() {
    const userEmail = document.getElementById("userEmail").value.trim().toLowerCase();
    
    // Security check: ensure environment is not tampered
    if (typeof window === 'undefined') return;

    try {
        // Communicate with the Cloudflare Backend
        const response = await fetch(`${BACKEND_URL}/?email=${encodeURIComponent(userEmail)}`);
        const data = await response.json();

        if (data.saldo > 0) {
            // Trigger the email dispatch
            await emailjs.send(SERVICE_ID, TEMPLATE_ID, {
                to_email: userEmail,
                validation_code: data.codigo
            });
            
            // Logic for the prompt and code validation
            const userCode = prompt("Enter verification code:");
            if (userCode === data.codigo.toString()) {
                navigateTo('setupGeral');
            }
        } else {
            navigateTo('paymentScreen');
        }
    } catch (err) {
        console.error("System Error", err);
    }
}
