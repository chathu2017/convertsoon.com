/**
 * PDF Tools - Client Side Logic (Updated)
 * Handles: Split, Merge, Compress, Rotate, Protect, Unlock
 * Security: XSS Prevention & Single File Enforcement
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- ELEMENT SELECTION ---
    const dropzone = document.getElementById('pdfDropzone');
    const fileInput = document.getElementById('pdfInput');
    const workspace = document.getElementById('pdfWorkspace');
    const uploadSection = document.getElementById('pdfUploadSection');
    const pagesGrid = document.getElementById('pagesGrid');
    const selectionInfo = document.getElementById('selectionInfo');
    const closeBtn = document.getElementById('closeWorkspaceBtn');
    const globalLoader = document.getElementById('globalLoader');

    // Views
    const viewSplit = document.getElementById('viewSplit');
    const viewCompress = document.getElementById('viewCompress');
    const viewSecurity = document.getElementById('viewSecurity');

    // Action Buttons
    const btnSplitMerge = document.getElementById('btnSplitMerge');
    const btnSplitZip = document.getElementById('btnSplitZip');
    const btnCompressRun = document.getElementById('btnCompressRun');
    const btnDeleteSelected = document.getElementById('btnDeleteSelected');
    const btnToggleSelectAll = document.getElementById('btnToggleSelectAll');
    const btnLoadMore = document.getElementById('btnLoadMore');
    const loadMoreContainer = document.getElementById('loadMoreContainer');

    // Security Elements (NEW)
    const securityFileCard = document.getElementById('securityFileCard');
    const securityFileName = document.getElementById('securityFileName');
    const securityStatusText = document.getElementById('securityStatusText');
    const securityIconContainer = document.getElementById('securityIconContainer');
    const pdfPasswordInput = document.getElementById('pdfPassword');
    const btnSecurityRun = document.getElementById('btnSecurityRun');
    const togglePassBtn = document.getElementById('togglePasswordVisibility');
    const passwordLabel = document.getElementById('passwordLabel');

    // Compression Controls
    const modeSelect = document.getElementById('compressModeSelect');
    const qualityInput = document.getElementById('compressQuality');
    const dpiInput = document.getElementById('compressDPI');
    const qualityText = document.getElementById('qualityValueText');
    const grayscaleInput = document.getElementById('compressGrayscale');

    // Range Selection Elements
    const toggleRangeBtn = document.getElementById('toggleRangeBtn');
    const rangeInputsContainer = document.getElementById('rangeInputsContainer');
    const startPageInput = document.getElementById('startPageInput');
    const endPageInput = document.getElementById('endPageInput');
    const btnSelectRange = document.getElementById('btnSelectRange');
    const rangeErrorText = document.getElementById('rangeErrorText');

    // --- STATE VARIABLES ---
    let currentJobId = null;
    let selectedPages = new Set();
    let currentTool = 'split'; // Default tool
    let totalPagesCount = 0;
    let rotationMap = {};
    
    // Lazy Load
    let allLoadedThumbnails = [];
    let renderedCount = 0;
    const BATCH_SIZE = 20;

    // Compress State
    let compressJobList = [];
    let completedJobIds = [];

    // Security State
    let isFileEncrypted = false; 

    // --- REFRESH PROTECTION: Restore State on Load ---
    restorePdfState();

    // --- TOAST NOTIFICATIONS ---
    function showToast(message, type = 'success') {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        let icon = type === 'success' ?
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>' :
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
        toast.innerHTML = `${icon}<span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // --- UPLOAD HANDLERS ---
    if (dropzone) {
        dropzone.addEventListener('click', (e) => {
            if (e.target !== fileInput) fileInput.click();
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (!files.length) return;

            // 1. SECURITY MODE (Strict Single File)
            if (currentTool === 'security') {
                if (files.length > 1) {
                    showToast("Please upload only ONE file for Lock/Unlock.", "error");
                    fileInput.value = '';
                    return;
                }
                handleSecurityUpload(files[0]);
            }
            // 2. COMPRESS MODE (Batch Upload)
            else if (currentTool === 'compress') {
                if (files.length > 10) {
                    showToast("Max 10 files allowed at once.", "error");
                    fileInput.value = '';
                    return;
                }
                handleCompressUploads(files);
            }
            // 3. SPLIT / MERGE MODE (Multi-File Support)
            else {
                if (files.length > 10) {
                    showToast("Max 10 files allowed for Merge/Split", "error");
                    return;
                }
                handleSplitUploads(files);
            }
        });
    }

    // --- FUNCTION: Handle Security Upload (NEW) ---
    async function handleSecurityUpload(file) {
        if (file.type !== 'application/pdf') {
            showToast("Only PDF files allowed!", "error");
            return;
        }
        if (file.size > 50 * 1024 * 1024) {
            showToast("File exceeds 50MB limit!", "error");
            return;
        }

        // Set Loading UI
        const dropzoneText = dropzone.querySelector('.dropzone-text');
        const btnUpload = dropzone.querySelector('.btn-upload');
        const originalBtnText = btnUpload.textContent;

        dropzoneText.textContent = "Analyzing Encryption...";
        dropzone.classList.add('disabled');
        btnUpload.disabled = true;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/pdf/analyze', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.success) {
                currentJobId = data.job_id;
                isFileEncrypted = data.is_encrypted; // Backend must send this

                // --- UI SETUP FOR SECURITY ---
                uploadSection.style.display = 'none';
                workspace.style.display = 'block';
                viewSecurity.style.display = 'block';
                viewSplit.style.display = 'none';
                viewCompress.style.display = 'none';

                securityFileCard.style.display = 'block';
                
                // SECURITY FIX: Prevent XSS using textContent
                securityFileName.textContent = file.name; 

                // Dynamic UI based on Encryption Status
                updateSecurityUI(isFileEncrypted);

                showToast("File Analyzed Successfully");
                
                // Save State
                savePdfState('security', { filename: file.name, isEncrypted: isFileEncrypted });

            } else {
                throw new Error(data.detail);
            }
        } catch (e) {
            console.error(e);
            showToast("Upload Failed: " + e.message, "error");
        } finally {
            // Reset Upload Button
            dropzone.classList.remove('disabled');
            dropzoneText.textContent = "Drag & Drop PDF here";
            btnUpload.disabled = false;
            btnUpload.textContent = originalBtnText;
            fileInput.value = '';
        }
    }

    function updateSecurityUI(isEncrypted) {
        if (isEncrypted) {
            // UNLOCK MODE
            securityIconContainer.innerHTML = `
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#ef4444" stroke-width="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>`; // Red Closed Lock
            securityStatusText.textContent = "This file is Password Protected.";
            securityStatusText.style.color = "#ef4444";
            
            passwordLabel.textContent = "Enter Password to Unlock";
            pdfPasswordInput.placeholder = "Enter current password...";
            btnSecurityRun.textContent = "Unlock PDF";
            btnSecurityRun.dataset.action = "unlock";
            btnSecurityRun.disabled = false;
            btnSecurityRun.style.background = "#ef4444"; // Red Button

        } else {
            // PROTECT MODE
            securityIconContainer.innerHTML = `
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#10b981" stroke-width="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 9.9-1"></path>
                </svg>`; // Green Open Lock
            securityStatusText.textContent = "File is Unlocked. Ready to Protect.";
            securityStatusText.style.color = "#10b981";

            passwordLabel.textContent = "Set New Password";
            pdfPasswordInput.placeholder = "Type a strong password...";
            btnSecurityRun.textContent = "Lock PDF";
            btnSecurityRun.dataset.action = "protect";
            btnSecurityRun.disabled = false;
            btnSecurityRun.style.background = "var(--color-accent)"; // Default Purple
        }
    }

    // --- SECURITY ACTION HANDLER ---
    if (btnSecurityRun) {
        btnSecurityRun.addEventListener('click', async () => {
            const password = pdfPasswordInput.value.trim();
            const action = btnSecurityRun.dataset.action; // 'protect' or 'unlock'

            if (!password) {
                showToast("Please enter a password!", "error");
                pdfPasswordInput.focus();
                return;
            }

            // Start Loading
            btnSecurityRun.disabled = true;
            btnSecurityRun.innerHTML = `<span class="spinner-border"></span> Processing...`;

            try {
                const res = await fetch('/api/pdf/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        job_id: currentJobId, 
                        action: action, 
                        params: { password: password } 
                    })
                });
                
                const data = await res.json();

                if (data.success) {
                    showToast(action === 'protect' ? "PDF Locked Successfully!" : "PDF Unlocked Successfully!");
                    window.location.href = data.download_url;
                    
                    // Reset UI
                    clearPdfState();
                    pdfPasswordInput.value = '';
                    setTimeout(() => {
                        // Optional: Reload or close workspace
                        // closeBtn.click(); 
                        btnSecurityRun.textContent = "Done! Download Started";
                        btnSecurityRun.style.background = "#10b981";
                    }, 1000);

                } else {
                    throw new Error(data.detail);
                }
            } catch (e) {
                showToast(e.message, "error");
                btnSecurityRun.textContent = "Try Again";
                btnSecurityRun.disabled = false;
            }
        });
    }

    // Toggle Password Visibility
    if (togglePassBtn) {
        togglePassBtn.addEventListener('click', () => {
            const type = pdfPasswordInput.getAttribute('type') === 'password' ? 'text' : 'password';
            pdfPasswordInput.setAttribute('type', type);
            // Toggle Icon opacity to show active state
            togglePassBtn.style.opacity = type === 'text' ? '1' : '0.6';
        });
    }


    // --- EXISTING FUNCTIONS (Unchanged mostly, just integrated) ---

    // --- FUNCTION: Handle Split/Merge Uploads ---
    async function handleSplitUploads(files) {
        let totalSize = 0;
        let validFiles = [];

        for (let file of files) {
            if (file.type !== 'application/pdf') {
                showToast(`Skipped ${file.name}: Not a PDF`, "error");
                continue;
            }
            totalSize += file.size;
            validFiles.push(file);
        }

        if (totalSize > 50 * 1024 * 1024) {
            showToast("Total file size exceeds 50MB limit!", "error");
            return;
        }

        if (validFiles.length === 0) return;

        const dropzoneText = dropzone.querySelector('.dropzone-text');
        const btnUpload = dropzone.querySelector('.btn-upload');
        const originalBtnText = btnUpload.textContent;

        dropzoneText.textContent = "Uploading...";
        dropzone.classList.add('disabled');
        dropzoneText.classList.add('analyzing-text');
        btnUpload.disabled = true;
        btnUpload.textContent = "Uploading...";

        const formData = new FormData();
        validFiles.forEach(file => {
            formData.append('file', file);
        });

        try {
            const res = await fetch('/api/pdf/analyze', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.success) {
                currentJobId = data.job_id;
                allLoadedThumbnails = data.thumbnails;
                totalPagesCount = allLoadedThumbnails.length;
                renderedCount = 0;
                rotationMap = {}; 
                pagesGrid.innerHTML = '';

                savePdfState('split');
                renderNextBatch();

                uploadSection.style.display = 'none';
                workspace.style.display = 'block';
                viewSplit.style.display = 'block';
                viewCompress.style.display = 'none';
                viewSecurity.style.display = 'none'; // Ensure security is hidden

                showToast("PDFs Uploaded Successfully");
                resetUploadState();
            } else {
                throw new Error(data.detail);
            }
        } catch (e) {
            console.error(e);
            showToast("Upload Failed: " + e.message, "error");
            resetUploadState();
        }

        function resetUploadState() {
            dropzone.classList.remove('disabled');
            if (currentTool === 'compress') dropzoneText.textContent = "Drag & Drop PDF to Compress";
            else if (currentTool === 'security') dropzoneText.textContent = "Drag & Drop PDF to Protect/Unlock";
            else dropzoneText.textContent = "Drag & Drop PDF to Split";
            
            dropzoneText.classList.remove('analyzing-text');
            btnUpload.disabled = false;
            btnUpload.textContent = originalBtnText;
            fileInput.value = '';
        }
    }

    // --- LAZY LOADING & RENDERING LOGIC ---
    if (btnLoadMore) {
        btnLoadMore.addEventListener('click', () => {
            renderNextBatch();
        });
    }

    function renderNextBatch() {
        const start = renderedCount;
        const end = Math.min(start + BATCH_SIZE, totalPagesCount);
        const batch = allLoadedThumbnails.slice(start, end);

        batch.forEach(thumb => {
            const card = createThumbnailCard(thumb);
            pagesGrid.appendChild(card);
        });

        renderedCount = end;
        startPageInput.max = totalPagesCount;
        endPageInput.max = totalPagesCount;
        endPageInput.placeholder = totalPagesCount;

        if (typeof Sortable !== 'undefined' && !pagesGrid.sortableInstance) {
            pagesGrid.sortableInstance = new Sortable(pagesGrid, {
                animation: 150,
                ghostClass: 'sortable-ghost',
                delay: 200,
                delayOnTouchOnly: true,
                touchStartThreshold: 3,
            });
        }

        if (renderedCount < totalPagesCount) {
            loadMoreContainer.style.display = 'block';
            btnLoadMore.textContent = `Load More (${totalPagesCount - renderedCount} remaining)...`;
        } else {
            loadMoreContainer.style.display = 'none';
        }

        updateUI();
    }

    function createThumbnailCard(thumb) {
        const card = document.createElement('div');
        card.className = 'pdf-page-card';
        card.dataset.page = thumb.page;
        card.style.cursor = "grab";

        // --- SAFE IMAGE LOADING ---
        const img = document.createElement('img');
        img.src = thumb.url;
        img.loading = "lazy";

        img.onerror = function() {
            this.style.display = 'none';
            const fallback = document.createElement('div');
            fallback.className = 'file-item-icon';
            fallback.style.cssText = "width:100%; height:100%; display:flex; align-items:center; justify-content:center; font-size:12px; color:#666; background:#f0f0f0;";
            fallback.innerText = `Page ${thumb.page}`;
            card.prepend(fallback);
        };

        const savedRotation = rotationMap[thumb.page] || 0;
        if (savedRotation > 0) {
            img.className = `rotate-${savedRotation}`;
        }

        const numLabel = document.createElement('div');
        numLabel.className = 'page-number';
        numLabel.textContent = thumb.page;

        const rotateBtn = document.createElement('div');
        rotateBtn.className = 'page-rotate-btn';
        rotateBtn.innerHTML = '🔄';
        rotateBtn.title = "Rotate";

        rotateBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const pageNum = parseInt(card.dataset.page);
            let currentRotation = rotationMap[pageNum] || 0;
            currentRotation = (currentRotation + 90) % 360;
            rotationMap[pageNum] = currentRotation;
            img.className = currentRotation > 0 ? `rotate-${currentRotation}` : '';
            savePdfState('split');
        });

        const closeBtnCard = document.createElement('div');
        closeBtnCard.className = 'page-close-btn';
        closeBtnCard.innerHTML = '✕';
        closeBtnCard.title = "Remove Page";

        closeBtnCard.addEventListener('click', (e) => {
            e.stopPropagation();
            card.remove();
            const pageNum = parseInt(card.dataset.page);
            if (selectedPages.has(pageNum)) {
                selectedPages.delete(pageNum);
            }
            updateUI();
        });

        card.appendChild(img);
        card.appendChild(numLabel);
        card.appendChild(rotateBtn);
        card.appendChild(closeBtnCard);

        card.addEventListener('click', () => {
            const pageNum = parseInt(card.dataset.page);
            if (selectedPages.has(pageNum)) {
                selectedPages.delete(pageNum);
                card.classList.remove('selected');
            } else {
                selectedPages.add(pageNum);
                card.classList.add('selected');
            }
            updateUI();
        });

        return card;
    }

    // --- RANGE SELECTION LOGIC ---
    if (toggleRangeBtn) {
        toggleRangeBtn.addEventListener('click', () => {
            const isHidden = rangeInputsContainer.style.display === 'none';
            rangeInputsContainer.style.display = isHidden ? 'block' : 'none';
            toggleRangeBtn.classList.toggle('active', isHidden);
        });
    }

    function validateRange() {
        const start = parseInt(startPageInput.value);
        const end = parseInt(endPageInput.value);
        const isValid = start > 0 && end > 0 && start <= end;
        btnSelectRange.disabled = !isValid;
        if (rangeErrorText) {
            rangeErrorText.style.display = (start > end) ? 'block' : 'none';
        }
    }

    if (startPageInput && endPageInput) {
        startPageInput.addEventListener('input', validateRange);
        endPageInput.addEventListener('input', validateRange);
    }

    if (btnSelectRange) {
        btnSelectRange.addEventListener('click', () => {
            const start = parseInt(startPageInput.value);
            const end = parseInt(endPageInput.value);
            let changesMade = false;

            const cards = document.querySelectorAll('.pdf-page-card');
            cards.forEach(card => {
                const pageNum = parseInt(card.dataset.page);
                if (pageNum >= start && pageNum <= end) {
                    if (!selectedPages.has(pageNum)) {
                        selectedPages.add(pageNum);
                        card.classList.add('selected');
                        changesMade = true;
                    }
                }
            });

            if (changesMade) {
                showToast(`Pages ${start}-${end} selected!`);
                updateUI();
                rangeInputsContainer.style.display = 'none';
                toggleRangeBtn.classList.remove('active');
            } else {
                showToast("No visible pages in that range", "error");
            }
        });
    }

    // --- BATCH DELETE LOGIC ---
    if (btnDeleteSelected) {
        btnDeleteSelected.addEventListener('click', () => {
            if (selectedPages.size === 0) return;
            if (!confirm(`Are you sure you want to remove ${selectedPages.size} pages?`)) return;

            const cards = document.querySelectorAll('.pdf-page-card');
            cards.forEach(card => {
                const pageNum = parseInt(card.dataset.page);
                if (selectedPages.has(pageNum)) {
                    card.remove();
                }
            });

            selectedPages.clear();
            updateUI();
            showToast("Selected pages removed.");
        });
    }

    // --- SMART TOGGLE LOGIC ---
    if (btnToggleSelectAll) {
        btnToggleSelectAll.addEventListener('click', () => {
            const visibleCards = document.querySelectorAll('.pdf-page-card');
            const totalVisible = visibleCards.length;
            let selectedVisibleCount = 0;
            visibleCards.forEach(card => {
                if (selectedPages.has(parseInt(card.dataset.page))) selectedVisibleCount++;
            });

            const isAllSelected = (selectedVisibleCount === totalVisible) && (totalVisible > 0);

            if (isAllSelected) {
                visibleCards.forEach(card => {
                    card.classList.remove('selected');
                    selectedPages.delete(parseInt(card.dataset.page));
                });
                showToast("Selection cleared");
            } else {
                visibleCards.forEach(card => {
                    const pageNum = parseInt(card.dataset.page);
                    selectedPages.add(pageNum);
                    card.classList.add('selected');
                });
                showToast("All visible pages selected");
            }
            updateUI();
        });
    }

    // --- UI UPDATE & BUTTON STATES ---
    function updateUI() {
        const count = selectedPages.size;
        selectionInfo.textContent = `${count} pages selected`;
        const hasSelection = count > 0;
        const visibleCards = document.querySelectorAll('.pdf-page-card');
        const visibleCount = visibleCards.length;

        if (btnToggleSelectAll) {
            let selectedVisibleCount = 0;
            visibleCards.forEach(card => {
                if (selectedPages.has(parseInt(card.dataset.page))) selectedVisibleCount++;
            });
            btnToggleSelectAll.textContent = (visibleCount > 0 && selectedVisibleCount === visibleCount) ? "Deselect All" : "Select All";
        }

        if (btnSplitMerge) {
            btnSplitMerge.disabled = visibleCount === 0;
            btnSplitMerge.style.opacity = visibleCount > 0 ? "1" : "0.5";
            btnSplitMerge.textContent = hasSelection ? (count === 1 ? "Download Selected" : "Merge & Download") : "Merge All";
        }

        if (btnSplitZip) {
            btnSplitZip.disabled = !hasSelection;
            btnSplitZip.style.opacity = hasSelection ? "1" : "0.5";
        }

        if (btnDeleteSelected) {
            btnDeleteSelected.disabled = !hasSelection;
        }
    }

    // --- SETTINGS DROPDOWN ANIMATION ---
    const toggleSettingsBtn = document.getElementById('toggleCompressSettings');
    const settingsContent = document.getElementById('compressSettingsContent');

    if (toggleSettingsBtn && settingsContent) {
        toggleSettingsBtn.addEventListener('click', () => {
            const isActive = toggleSettingsBtn.classList.contains('active');
            toggleSettingsBtn.classList.toggle('active');
            if (!isActive) {
                settingsContent.style.maxHeight = settingsContent.scrollHeight + "px";
            } else {
                settingsContent.style.maxHeight = "0px";
            }
        });
    }

    // --- COMPRESSION UI HANDLERS ---
    if (modeSelect) {
        modeSelect.addEventListener('change', () => {
            const val = modeSelect.value;
            if (val === 'custom') {
                qualityInput.disabled = false;
                dpiInput.disabled = false;
            } else {
                qualityInput.disabled = true;
                dpiInput.disabled = true;
                if (val === 'medium') { qualityInput.value = 75; dpiInput.value = 150; }
                if (val === 'high') { qualityInput.value = 50; dpiInput.value = 96; }
                if (qualityText) qualityText.textContent = qualityInput.value + '%';
            }
        });
    }

    if (qualityInput) {
        qualityInput.addEventListener('input', () => {
            if (qualityText) qualityText.textContent = qualityInput.value + '%';
        });
    }

    // --- CLOSE WORKSPACE ---
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (confirm("Close workspace and clear files?")) {
                if (currentJobId) fetch(`/api/cleanup/${currentJobId}`, { method: 'POST' });
                clearPdfState();
                workspace.style.display = 'none';
                uploadSection.style.display = 'block';

                const dropText = dropzone.querySelector('.dropzone-text');
                if (currentTool === 'compress') dropText.textContent = "Drag & Drop PDF to Compress";
                else if (currentTool === 'security') dropText.textContent = "Drag & Drop PDF to Protect/Unlock";
                else dropText.textContent = "Drag & Drop PDF to Split";

                fileInput.value = '';
                currentJobId = null;
                selectedPages.clear();
                rotationMap = {};
                allLoadedThumbnails = [];
                rangeInputsContainer.style.display = 'none';
                if (toggleRangeBtn) toggleRangeBtn.classList.remove('active');

                if (btnCompressRun) {
                    btnCompressRun.dataset.mode = "compress";
                    btnCompressRun.style.background = "";
                }
                completedJobIds = [];
            }
        });
    }

    // --- TAB SWITCHING (UPDATED) ---
    // --- TAB SWITCHING (FIXED: FULL STATE RESET) ---
    document.querySelectorAll('.tool-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            // 1. UI එකේ Active Class එක මාරු කිරීම
            document.querySelectorAll('.tool-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // 2. අලුත් Tool එක සෙට් කිරීම
            currentTool = btn.dataset.tool;

            // 3. SUPER CLEANUP (මේක තමයි වැදගත්ම කොටස) 🔥
            // ටැබ් මාරු වෙද්දි පරණ කුණු (Data) ඔක්කොම සුද්ද කරනවා.
            clearPdfState(); // LocalStorage Clear
            currentJobId = null;
            selectedPages.clear();
            compressJobList = [];
            completedJobIds = [];
            rotationMap = {};
            allLoadedThumbnails = [];
            
            // UI එක සුද්ද කිරීම
            pagesGrid.innerHTML = '';
            const compressContainer = document.getElementById('compressFilesContainer');
            if(compressContainer) compressContainer.innerHTML = '';
            if(securityFileName) securityFileName.textContent = '';
            if(pdfPasswordInput) pdfPasswordInput.value = '';
            
            // Range Inputs හංගනවා
            if(rangeInputsContainer) {
                rangeInputsContainer.style.display = 'none';
                if(toggleRangeBtn) toggleRangeBtn.classList.remove('active');
            }

            // 4. File Input එක Reset කිරීම (Single vs Multiple)
            fileInput.value = ''; // කලින් තෝරපු ෆයිල් අයින් කරනවා
            
            if (currentTool === 'security') {
                fileInput.removeAttribute('multiple'); // Security නම් එකයි
            } else {
                fileInput.setAttribute('multiple', ''); // අනිත් ඒවාට ගොඩක් පුළුවන්
            }

            // 5. Workspace එක වහලා Upload Section එක පෙන්නනවා
            // (එතකොට යූසර්ට මුල ඉඳන්ම පිරිසිදුව පටන් ගන්න පුළුවන්)
            workspace.style.display = 'none';
            uploadSection.style.display = 'block';

            // 6. Dropzone Text එක මාරු කිරීම
            const dropText = dropzone.querySelector('.dropzone-text');
            if (dropText) {
                if (currentTool === 'compress') dropText.textContent = "Drag & Drop PDF to Compress";
                else if (currentTool === 'security') dropText.textContent = "Drag & Drop PDF to Protect/Unlock";
                else dropText.textContent = "Drag & Drop PDF to Split";
            }

            // 7. අදාල View එක ලෑස්ති කරලා තියනවා (Upload කළාම පෙන්නන්න)
            viewSplit.style.display = currentTool === 'split' ? 'block' : 'none';
            viewCompress.style.display = currentTool === 'compress' ? 'block' : 'none';
            viewSecurity.style.display = currentTool === 'security' ? 'block' : 'none';
        });
    });

    // --- FUNCTION: Handle Batch Uploads for Compress ---
    async function handleCompressUploads(files) {
        let totalBatchSize = 0;
        const validFiles = [];

        for (let file of files) {
            if (file.type !== 'application/pdf') {
                showToast(`Skipped ${file.name}: Not a PDF`, "error");
                continue;
            }
            totalBatchSize += file.size;
            validFiles.push(file);
        }

        if (totalBatchSize > 50 * 1024 * 1024) {
            showToast(`Total size exceeds 50MB limit!`, "error");
            if(fileInput) fileInput.value = '';
            return;
        }

        if (validFiles.length === 0) return;

        const btnCompress = document.getElementById('btnCompressRun');
        let btnCompressRunLocal = btnCompress || document.querySelector('#viewCompress .convert-btn');

        if (btnCompressRunLocal) {
            btnCompressRunLocal.className = 'convert-btn';
            btnCompressRunLocal.style.background = "";
            btnCompressRunLocal.textContent = 'Analyzing PDFs...';
            btnCompressRunLocal.disabled = true;
            btnCompressRunLocal.style.opacity = '0.7';
            btnCompressRunLocal.style.cursor = 'wait';
        }

        compressJobList = [];
        completedJobIds = [];
        const container = document.getElementById('compressFilesContainer');
        if(container) container.innerHTML = '';

        uploadSection.style.display = 'none';
        workspace.style.display = 'block';
        
        viewSplit.style.display = 'none';
        viewCompress.style.display = 'block';
        viewSecurity.style.display = 'none';

        const uploadQueue = [];
        
        for (let file of validFiles) {
            const cardId = `card-${Math.random().toString(36).substr(2, 9)}`;
            const card = document.createElement('div');
            card.className = 'file-summary-card';
            card.id = cardId;
            card.style.cssText = 'display: flex; align-items: center; background: var(--color-surface); padding: 15px; border-radius: 12px; border: 1px solid var(--color-border); margin-bottom: 10px; gap: 15px;';
            card.innerHTML = `
                <div class="file-thumb" style="width: 50px; height: 70px; background: #f0f0f0; border-radius: 6px; overflow: hidden; border: 1px solid var(--color-border); display:flex; align-items:center; justify-content:center; color:#666; flex-shrink: 0;">
                     <div style="font-size:20px;">📄</div>
                </div>
                <div class="file-details" style="flex: 1; min-width: 0; padding-right: 15px;">
                    <h4 class="file-name-text" style="margin: 0 0 5px 0; font-size: 0.95rem; color: var(--color-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"></h4>
                    <span style="font-size: 0.8rem; color: var(--color-text-muted);">${(file.size / (1024 * 1024)).toFixed(2)} MB</span>
                </div>
                <div class="actions-area" style="display: flex; align-items: center; gap: 10px; margin-left: auto; flex-shrink: 0; min-width: 100px; justify-content: flex-end;">
                    <span class="status-badge" style="color: var(--color-text-muted); font-size: 0.85rem;">Ready</span>
                </div>
            `;
            // Security: Safe insertion
            card.querySelector('.file-name-text').textContent = file.name;
            container.appendChild(card);
            uploadQueue.push({ file: file, cardId: cardId });
        }

        for (let item of uploadQueue) {
            await processSingleUpload(item.file, item.cardId);
        }

        savePdfState('compress');

        if (btnCompressRunLocal) {
            btnCompressRunLocal.disabled = false;
            btnCompressRunLocal.textContent = "Start Compression";
            btnCompressRunLocal.style.opacity = "1";
            btnCompressRunLocal.style.cursor = "pointer";
        }
    }

    async function processSingleUpload(file, cardId) {
        const card = document.getElementById(cardId);
        if (!card) return;
        const statusBadge = card.querySelector('.status-badge');
        if(statusBadge) statusBadge.textContent = "Uploading...";

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/pdf/analyze', { method: 'POST', body: formData });
            const data = await res.json();

            if (res.ok && data.success) {
                const thumbImg = data.thumbnails && data.thumbnails.length > 0 ? `<img src="${data.thumbnails[0].url}" style="width:100%; height:100%; object-fit:cover;">` : '';
                card.querySelector('.file-thumb').innerHTML = thumbImg;
                if(statusBadge) {
                    statusBadge.textContent = 'Ready';
                    statusBadge.style.color = 'var(--color-success)';
                }
                compressJobList.push({
                    job_id: data.job_id,
                    card_id: cardId,
                    filename: file.name
                });
            } else {
                const errorMsg = data.detail || "Analysis Failed";
                if(statusBadge) {
                    statusBadge.textContent = "Error";
                    statusBadge.style.color = "red";
                    statusBadge.title = errorMsg;
                }
                showToast(errorMsg, "error");
            }
        } catch (e) {
            console.error(e);
            if(statusBadge) {
                statusBadge.textContent = "Net Error";
                statusBadge.style.color = "red";
            }
            showToast("Network Error", "error");
        }
    }

    // --- MAIN PROCESSING LOGIC ---
    if (btnSplitMerge) btnSplitMerge.addEventListener('click', () => processAction('split', 'merge'));
    if (btnSplitZip) btnSplitZip.addEventListener('click', () => processAction('split', 'zip'));

    if (btnCompressRun) {
        btnCompressRun.addEventListener('click', () => {
            if (btnCompressRun.dataset.mode === 'download') {
                downloadAllZip();
            } else {
                processAction('compress', 'default');
            }
        });
    }

    // --- UPDATED: Save-then-Download Logic for ZIP ---
    async function downloadAllZip() {
        if (completedJobIds.length === 0) return;
        showToast("Zipping files... 🗜️", "processing");
        globalLoader.style.display = 'block';
        
        try {
            const res = await fetch('/api/download-zip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_ids: completedJobIds })
            });

            const data = await res.json();

            if (res.ok && data.success && data.download_url) {
                showToast("Download started!");
                window.location.href = data.download_url;
                clearPdfState();
            } else {
                showToast("Zip generation failed", "error");
            }
        } catch(e) {
            console.error(e);
            showToast("Download Error: " + e.message, "error");
        } finally {
            globalLoader.style.display = 'none';
        }
    }

    // --- 3. MAIN ACTION HANDLER (Updated Logic) ---
    async function processAction(action, mode) {
        if (action === 'split') {
            if (!currentJobId) return;
            globalLoader.style.display = 'block';

            const orderedPages = [];
            const visibleCards = document.querySelectorAll('.pdf-page-card');
            if (selectedPages.size > 0) {
                visibleCards.forEach(card => {
                    if (selectedPages.has(parseInt(card.dataset.page))) orderedPages.push(parseInt(card.dataset.page));
                });
            } else {
                visibleCards.forEach(card => orderedPages.push(parseInt(card.dataset.page)));
            }

            if (orderedPages.length === 0) {
                showToast("No pages to process", "error");
                globalLoader.style.display = 'none';
                return;
            }

            const params = { pages: orderedPages, split_mode: mode, rotations: rotationMap };

            try {
                const res = await fetch('/api/pdf/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ job_id: currentJobId, action: action, params: params })
                });
                const data = await res.json();
                if (data.success) {
                    showToast("Done! Downloading...");
                    window.location.href = data.download_url;
                    clearPdfState();
                } else throw new Error(data.detail);
            } catch (e) { showToast(e.message, "error"); }
            finally { globalLoader.style.display = 'none'; }
        }

        // --- B. COMPRESS LOGIC---
        else if (action === 'compress') {
            
            if (btnCompressRun && btnCompressRun.classList.contains('completed')) {
                downloadAllZip(); 
                return;
            }

            if (compressJobList.length === 0) {
                showToast("No files to compress!", "error");
                return;
            }

            globalLoader.style.display = 'none'; 
            showToast("Starting compression... ⚙️", "processing");

            if (btnCompressRun) startLiquidProgress(btnCompressRun);

            const modeSelectVal = modeSelect ? modeSelect.value : 'medium';
            const params = {
                compression_level: modeSelectVal,
                custom_mode: (modeSelectVal === 'custom'),
                quality: qualityInput ? qualityInput.value : 75,
                dpi: dpiInput ? dpiInput.value : 150,
                grayscale: grayscaleInput ? grayscaleInput.checked : false
            };

            let completed = 0;
            completedJobIds = [];
            const totalFiles = compressJobList.length;

            for (let i = 0; i < totalFiles; i++) {
                let job = compressJobList[i];
                const card = document.getElementById(job.card_id);
                
                const percent = Math.round(((i + 1) / totalFiles) * 100);
                if (btnCompressRun) {
                    updateLiquidProgress(btnCompressRun, percent, `Compressing (${i+1}/${totalFiles})...`);
                }

                if (card) {
                    const statusSpan = card.querySelector('.status-badge');
                    if (statusSpan) { statusSpan.textContent = "Processing..."; statusSpan.style.color = "var(--color-accent)"; }
                }

                try {
                    const res = await fetch('/api/pdf/process', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_id: job.job_id, action: 'compress', params: params })
                    });
                    const data = await res.json();

                    if (data.success) {
                        let sizeDisplay = "";
                        if (data.file_size) {
                            const sizeMB = (data.file_size / (1024 * 1024)).toFixed(2);
                            sizeDisplay = `<span style="color: #00c851; font-weight: 700; font-size: 0.9rem; margin-right: 15px;">${sizeMB} MB</span>`;
                        }

                        if (card) {
                            const actionsArea = card.querySelector('.actions-area');
                            actionsArea.innerHTML = `
                                ${sizeDisplay}
                                <a href="${data.download_url}" class="download-mini-btn" style="text-decoration:none; background:var(--color-accent); color:white; padding:5px 12px; border-radius:4px; font-size:0.8rem; display:inline-block;">Download ↓</a>
                            `;
                        }
                        completed++;
                        completedJobIds.push(job.job_id);
                    } else {
                        if (card) {
                            const statusSpan = card.querySelector('.status-badge');
                            if (statusSpan) { statusSpan.textContent = "Failed"; statusSpan.style.color = "red"; }
                        }
                    }
                } catch (e) {
                    console.error(e);
                    if (card) {
                        const statusSpan = card.querySelector('.status-badge');
                        if (statusSpan) { statusSpan.textContent = "Error"; statusSpan.style.color = "red"; }
                    }
                }
            }

            clearPdfState();
            
            if (btnCompressRun) {
                if (completed > 0) {
                    finishLiquidProgress(btnCompressRun, completed > 1);
                    showToast(`Finished! ${completed} files.`);
                } else {
                    showToast("Compression failed.", "error");
                    btnCompressRun.className = 'convert-btn';
                    btnCompressRun.innerHTML = 'Retry Compression';
                    btnCompressRun.disabled = false;
                }
            }
        }
    }

    // --- REFRESH RESTORE LOGIC ---
    function savePdfState(toolType, extraData = {}) {
        if (toolType === 'split') {
            const state = { tool: 'split', jobId: currentJobId, thumbnails: allLoadedThumbnails, rotationMap: rotationMap };
            localStorage.setItem('pdf_active_job', JSON.stringify(state));
        } else if (toolType === 'compress') {
            const state = { tool: 'compress', compressList: compressJobList };
            localStorage.setItem('pdf_active_job', JSON.stringify(state));
        } else if (toolType === 'security') {
            const state = { tool: 'security', jobId: currentJobId, ...extraData };
            localStorage.setItem('pdf_active_job', JSON.stringify(state));
        }
    }

    function clearPdfState() {
        localStorage.removeItem('pdf_active_job');
    }

    function restorePdfState() {
        const stored = localStorage.getItem('pdf_active_job');
        if (!stored) return;

        try {
            const state = JSON.parse(stored);

            // --- 1. INTERNAL HELPER: Tab එක Active කරනවා (Click Event එක Trigger නොවී) ---
            const updateTabUI = (toolName) => {
                // පරණ Active Tabs අයින් කරනවා
                document.querySelectorAll('.tool-tab').forEach(b => b.classList.remove('active'));
                
                // අදාල Tool එකට Active Class එක දානවා
                const btn = document.querySelector(`.tool-tab[data-tool="${toolName}"]`);
                if (btn) btn.classList.add('active');
            };

            // --- 2. INTERNAL HELPER: Workspace එක පෙන්නන විදිය ---
            const showWorkspaceUI = (activeViewId) => {
                // Upload Section හංගලා Workspace පෙන්නනවා
                if (uploadSection) uploadSection.style.display = 'none';
                if (workspace) workspace.style.display = 'block';

                // ඔක්කොම Views හංගනවා
                if (viewSplit) viewSplit.style.display = 'none';
                if (viewCompress) viewCompress.style.display = 'none';
                if (viewSecurity) viewSecurity.style.display = 'none';

                // අදාල View එක විතරක් පෙන්නනවා
                const targetView = document.getElementById(activeViewId);
                if (targetView) targetView.style.display = 'block';
            };

            // --- 3. SPLIT MODE RESTORE ---
            if (state.tool === 'split') {
                if (!state.jobId || !state.thumbnails || state.thumbnails.length === 0) {
                    throw new Error("Invalid Split State");
                }

                currentJobId = state.jobId;
                allLoadedThumbnails = state.thumbnails;
                totalPagesCount = allLoadedThumbnails.length;
                rotationMap = state.rotationMap || {};
                renderedCount = 0;
                currentTool = 'split';

                // UI Updates
                updateTabUI('split');
                showWorkspaceUI('viewSplit');
                
                // Render Thumbnails
                if (pagesGrid) {
                    pagesGrid.innerHTML = '';
                    renderNextBatch();
                }
                showToast("Restored previous session");

            } 
            // --- 4. COMPRESS MODE RESTORE ---
            else if (state.tool === 'compress') {
                if (!state.compressList || state.compressList.length === 0) {
                    throw new Error("Invalid Compress State");
                }

                compressJobList = state.compressList;
                currentTool = 'compress';

                // UI Updates
                updateTabUI('compress');
                showWorkspaceUI('viewCompress');

                // Re-render File Cards
                const container = document.getElementById('compressFilesContainer');
                if (container) {
                    container.innerHTML = '';
                    
                    state.compressList.forEach(job => {
                        const card = document.createElement('div');
                        card.className = 'file-summary-card';
                        card.id = job.card_id;
                        card.style.cssText = 'display: flex; align-items: center; background: var(--color-surface); padding: 15px; border-radius: 12px; border: 1px solid var(--color-border); margin-bottom: 10px; gap: 15px;';
                        
                        const safeNameId = `restore-name-${job.card_id}`;
                        card.innerHTML = `
                            <div class="file-thumb" style="width: 50px; height: 70px; background: #f0f0f0; border-radius: 6px; overflow: hidden; border: 1px solid var(--color-border); display:flex; align-items:center; justify-content:center; color:#666; flex-shrink: 0;">
                                 <div style="font-size:20px;">📄</div>
                            </div>
                            <div class="file-details" style="flex: 1; min-width: 0; padding-right: 15px;">
                                <h4 id="${safeNameId}" style="margin: 0 0 5px 0; font-size: 0.95rem; color: var(--color-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"></h4>
                                <span style="font-size: 0.8rem; color: var(--color-text-muted);">Ready to Compress</span>
                            </div>
                            <div class="actions-area" style="display: flex; align-items: center; gap: 10px; margin-left: auto; flex-shrink: 0; min-width: 100px; justify-content: flex-end;">
                                <span class="status-badge" style="color: var(--color-success); font-size: 0.85rem;">Restored</span>
                            </div>
                        `;
                        const nameEl = card.querySelector(`#${safeNameId}`);
                        if (nameEl) nameEl.textContent = job.filename; // Prevent XSS
                        container.appendChild(card);
                    });
                }

                // Activate Button
                const btnCompressRunLocal = document.getElementById('btnCompressRun');
                if (btnCompressRunLocal) {
                    btnCompressRunLocal.disabled = false;
                    btnCompressRunLocal.textContent = "Compress PDF";
                    btnCompressRunLocal.style.opacity = "1";
                    btnCompressRunLocal.style.cursor = "pointer";
                    // Reset class if it was in 'completed' state previously
                    btnCompressRunLocal.className = 'convert-btn';
                }

                showToast("Restored previous session");

            } 
            // --- 5. SECURITY MODE RESTORE ---
            else if (state.tool === 'security') {
                if (!state.jobId) {
                    throw new Error("Invalid Security State");
                }

                currentJobId = state.jobId;
                currentTool = 'security';
                isFileEncrypted = state.isEncrypted;

                // UI Updates
                updateTabUI('security');
                showWorkspaceUI('viewSecurity');

                if (securityFileCard) securityFileCard.style.display = 'block';
                if (securityFileName) securityFileName.textContent = state.filename || "Restored File";
                
                // Update Lock/Unlock UI
                if (typeof updateSecurityUI === 'function') {
                    updateSecurityUI(isFileEncrypted);
                }

                showToast("Restored security session");
            }

        } catch (e) {
            console.error("Failed to restore PDF state:", e);
            // Data එක corrupt වෙලා නම් විතරක් clear කරනවා
            clearPdfState();
            // UI එක reset කරනවා
            if (uploadSection) uploadSection.style.display = 'block';
            if (workspace) workspace.style.display = 'none';
        }
    }

    // --- NEW: LIQUID NEON HELPER FUNCTIONS (For Compress Button) ---
    function startLiquidProgress(btn) {
        btn.classList.add('btn-progress-mode');
        btn.innerHTML = `
            <div class="neon-bar" style="width: 5%"></div>
            <div class="progress-text-overlay">
                <span id="progressIcon">🚀</span> <span id="progressText">Initializing...</span>
            </div>
        `;
        btn.disabled = true;
    }

    function updateLiquidProgress(btn, percent, text) {
        const bar = btn.querySelector('.neon-bar');
        const txt = document.getElementById('progressText');
        const icon = document.getElementById('progressIcon');
        
        if (bar) bar.style.width = `${percent}%`;
        if (txt) txt.textContent = text;
        if (percent > 30 && icon) icon.textContent = "⚡";
        if (percent > 80 && icon) icon.textContent = "✨";
    }

    function finishLiquidProgress(btn, isMultiple) {
        const bar = btn.querySelector('.neon-bar');
        const txt = document.getElementById('progressText');
        const icon = document.getElementById('progressIcon');

        if (bar) bar.style.width = '100%';
        btn.classList.add('completed');
        
        if (txt) txt.textContent = isMultiple ? "Download All (ZIP)" : "Download PDF";
        if (icon) icon.textContent = "✅";
        
        btn.disabled = false; 
        btn.style.cursor = "pointer";
        btn.style.pointerEvents = "auto";
    }
});
