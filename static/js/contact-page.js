/**
 * Contact Page Specific Logic
 * Handles: Contact Form Submission only.
 * Theme & FAQ logic is removed to prevent conflicts with global app.js
 */

document.addEventListener('DOMContentLoaded', () => {
    
    // Contact Form Logic Only
    const contactForm = document.getElementById('contactForm');
    
    if (contactForm) {
        contactForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const submitBtn = document.getElementById('submitBtn');
            const btnText = submitBtn.querySelector('.btn-text');
            const btnLoading = submitBtn.querySelector('.btn-loading');
            const successMsg = document.getElementById('successMessage');
            const errorMsg = document.getElementById('errorMessage');

            // Reset messages
            successMsg.style.display = 'none';
            errorMsg.style.display = 'none';

            // Show Loading State
            if (btnText) btnText.style.display = 'none';
            if (btnLoading) btnLoading.style.display = 'inline-flex';
            submitBtn.disabled = true;

            try {
                // --- API CALL SIMULATION ---
                // Replace this with your actual backend endpoint if needed
                await new Promise(resolve => setTimeout(resolve, 1500)); 
                
                // Assuming success:
                contactForm.style.display = 'none';
                successMsg.style.display = 'flex';
                contactForm.reset();

            } catch (error) {
                console.error('Error submitting form:', error);
                errorMsg.style.display = 'flex';
                
                // Restore Button
                if (btnText) btnText.style.display = 'inline';
                if (btnLoading) btnLoading.style.display = 'none';
                submitBtn.disabled = false;
            }
        });
    }
});
