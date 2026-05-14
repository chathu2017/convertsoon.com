/**
 * FileConverter - Frontend JavaScript with Bulk Upload Support
 * Features: ZIP Download (Save-then-Download), Auto-Cleanup, Wait-for-Completion
 * Plus: Theme Switcher (Dark/Light) & pSEO Auto-Selection
 * Plus: Smart "Convert -> Download" Button Transformation
 * Plus: Enhanced UX Notifications (Uploading/Processing States)
 * Plus: Refresh Protection (State Recovery)
 * Plus: AI Premium Pop-up Logic (Liquid Neon Bar Added)
 */

// === Theme Switcher Logic (Global Scope) ===
(function() {
    function initTheme() {
        const toggleBtn = document.getElementById('themeToggle');
        const themeIcon = document.getElementById('themeIcon');
        const root = document.documentElement;

        // 1. Check Saved Theme or System Preference
        const storedTheme = localStorage.getItem('theme');
        const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

        let currentTheme = storedTheme || (systemPrefersDark ? 'dark' : 'light');

        // 2. Apply Theme Function
        function applyTheme(theme) {
            root.setAttribute('data-theme', theme);
            updateIcon(theme);
        }

        // 3. Update Icon (Sun vs Moon)
        function updateIcon(theme) {
            if (!themeIcon) return;
            if (theme === 'dark') {
                // Moon Icon
                themeIcon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
            } else {
                // Sun Icon
                themeIcon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
            }
        }

        // Apply on load
        applyTheme(currentTheme);

        // 4. Toggle Event
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                currentTheme = currentTheme === 'light' ? 'dark' : 'light';
                applyTheme(currentTheme);
                localStorage.setItem('theme', currentTheme); // Save to browser memory
            });
        }
    }

    // Run when DOM is ready
    document.addEventListener('DOMContentLoaded', initTheme);
})();


// === Main Upload Logic (Protected Scope) ===
(function() {
    'use strict';

    const CONFIG = {
        pollInterval: 1000,
        maxPolls: 300
    };

    const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif', 'heic', 'heif', 'svg']);
    const DOCUMENT_EXTENSIONS = new Set(['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'html', 'htm', 'odt', 'epub', 'pdf']);

    const OUTPUT_FORMATS = {
        image: ['jpg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'pdf', 'svg'],
        document: ['pdf', 'png', 'jpg'],
        pdf: ['docx', 'xlsx', 'png', 'jpg', 'tiff', 'pdf'] // Added xlsx support
    };

    // Store for all selected files
    let fileQueue = {};
    let selectedOutputFormat = null;
    let isProcessing = false;

    let elements = {};

    function init() {
        const formEl = document.getElementById('uploadForm');
        // Only run upload logic if upload form exists (i.e., on Home page)
        if (formEl) {
            cacheElements();
            bindEvents();
            
            // --- REFRESH PROTECTION: Restore interrupted jobs ---
            restoreActiveJobs(); 
        }
    }

    function cacheElements() {
        elements = {
            form: document.getElementById('uploadForm'),
            dropzone: document.getElementById('dropzone'),
            fileInput: document.getElementById('fileInput'),
            fileListArea: document.getElementById('fileListArea'),
            fileList: document.getElementById('fileList'),
            clearAllBtn: document.getElementById('clearAllBtn'),

            optionsSection: document.getElementById('optionsSection'),
            formatGrid: document.getElementById('formatGrid'),
            optionsToggle: document.getElementById('optionsToggle'),
            advancedOptions: document.getElementById('advancedOptions'),

            vectorOptions: document.getElementById('vectorOptions'),
            standardOptions: document.getElementById('standardOptions'),

            convertBtn: document.getElementById('convertBtn'),
            btnText: document.querySelector('.btn-text'),
            btnLoader: document.querySelector('.btn-loader'),
            btnStatus: document.querySelector('.btn-status'),

            queueStatus: document.getElementById('queueStatus'),

            quality: document.getElementById('quality'),
            qualityValue: document.getElementById('qualityValue'),
            qualityOption: document.getElementById('qualityOption'),
            bgColor: document.getElementById('bgColor'),
            bgColorText: document.getElementById('bgColorText'),
            bgColorOption: document.getElementById('bgColorOption'),
            compressionLevel: document.getElementById('compressionLevel'),
            maxDimension: document.getElementById('maxDimension')
        };
    }

    function bindEvents() {
        elements.dropzone.addEventListener('click', (e) => {
            if (e.target !== elements.fileInput) {
                e.preventDefault();
                elements.fileInput.click();
            }
        });

        elements.fileInput.addEventListener('change', handleFileSelect);

        elements.clearAllBtn.addEventListener('click', () => resetAll(true));


        elements.dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            elements.dropzone.classList.add('dragover');
        });
        elements.dropzone.addEventListener('dragleave', () => {
            elements.dropzone.classList.remove('dragover');
        });
        elements.dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            elements.dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                handleFiles(e.dataTransfer.files);
            }
        });

        elements.optionsToggle.addEventListener('click', () => {
            const open = elements.advancedOptions.style.display !== 'none';
            elements.advancedOptions.style.display = open ? 'none' : 'block';
            elements.optionsToggle.classList.toggle('active', !open);
        });

        elements.quality.addEventListener('input', () => {
            elements.qualityValue.textContent = elements.quality.value + '%';
        });

        elements.bgColor.addEventListener('input', () => {
            elements.bgColorText.value = elements.bgColor.value;
        });
        elements.bgColorText.addEventListener('input', () => {
            if (/^#[0-9A-Fa-f]{6}$/.test(elements.bgColorText.value)) {
                elements.bgColor.value = elements.bgColorText.value;
            }
        });

        elements.form.addEventListener('submit', handleBulkSubmit);
    }

    function handleFileSelect(e) {
        if (e.target.files.length) {
            handleFiles(e.target.files);
        }
        elements.fileInput.value = '';
    }

    function handleFiles(files) {
        // --- 1. EXISTING: FILE COUNT LIMIT CHECK (MAX 10 FILES) ---
        const MAX_FILE_COUNT = 10;
        const currentCount = Object.keys(fileQueue).length;
        const newCount = files.length;

        if (currentCount + newCount > MAX_FILE_COUNT) {
            showToast(`Limit Reached: You can only upload up to ${MAX_FILE_COUNT} files at a time!`, "error");
            return;
        }

        // --- 2. EXISTING: TOTAL SIZE LIMIT CHECK (MAX 50MB) ---
        let currentQueueSize = 0;
        Object.values(fileQueue).forEach(item => {
            currentQueueSize += item.file.size;
        });

        let newFilesSize = 0;
        Array.from(files).forEach(file => {
            newFilesSize += file.size;
        });

        const MAX_TOTAL_LIMIT = 50 * 1024 * 1024; // 50MB in bytes

        if (currentQueueSize + newFilesSize > MAX_TOTAL_LIMIT) {
            let remaining = MAX_TOTAL_LIMIT - currentQueueSize;
            if (remaining < 0) remaining = 0;

            showToast(`Total limit exceeded! You only have space for ${formatSize(remaining)} more.`, "error");
            return;
        }

        // --- 3. UI UPDATES & PROCESSING ---
        elements.dropzone.style.display = 'none';
        elements.fileListArea.style.display = 'block';
        elements.optionsSection.style.display = 'flex';

        const BLOCKED_EXTENSIONS = ['.exe', '.sh', '.bat', '.cmd', '.msi', '.bin', '.scr', '.vbs', '.js', '.php', '.pl', '.py'];

        Array.from(files).forEach(file => {
            const fileName = file.name.toLowerCase();
            const ext = fileName.substring(fileName.lastIndexOf('.'));

            // Security Check
            if (BLOCKED_EXTENSIONS.includes(ext)) {
                showToast(`Security Alert: "${file.name}" is not allowed!`, "error");
                return;
            }

            // Single File Size Check (Safety Net)
            if (file.size > MAX_TOTAL_LIMIT) {
                showToast(`File "${file.name}" is too large! Max 50MB.`, "error");
                return;
            }

            // Add to Queue
            const fileId = Math.random().toString(36).substring(7);
            fileQueue[fileId] = {
                id: fileId,
                file: file,
                status: 'pending',
                progress: 0
            };
            addFileToList(fileQueue[fileId]);
        });

        // Load Formats based on first file
        if (Object.keys(fileQueue).length > 0) {
             if (!selectedOutputFormat) {
                const firstFile = Object.values(fileQueue)[0].file;
                const ext = getExtension(firstFile.name);
                populateFormats(ext);

                // --- NEW: pSEO AUTO-SELECT LOGIC ---
                // Detects 'data-pre-select' from <body> and auto-clicks that format
                const preSelected = document.body.dataset.preSelect;
                if (preSelected && preSelected !== 'None') {
                    const fmtBtn = document.querySelector(`.format-btn[data-format="${preSelected}"]`);
                    if (fmtBtn) {
                        fmtBtn.click(); // Trigger logic to select format
                        console.log("Auto-selected format for SEO:", preSelected);
                    }
                }
                // ------------------------------------
            }
        }

        updateConvertButton();
    }

    function addFileToList(fileObj) {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.id = `file-${fileObj.id}`;

        const ext = getExtension(fileObj.file.name);

        // --- Thumbnail Logic ---
        let iconHTML;
        if (fileObj.file.type && fileObj.file.type.startsWith('image/') && (fileObj.file instanceof Blob || fileObj.file instanceof File)) {
            const imgURL = URL.createObjectURL(fileObj.file);
            iconHTML = `<img src="${imgURL}" class="file-item-thumb" alt="preview" loading="lazy">`;
        } else {
            iconHTML = `<div class="file-item-icon">${ext.toUpperCase()}</div>`;
        }
        item.innerHTML = `
            ${iconHTML}
            <div class="file-item-info">
                <div class="file-item-name" id="name-${fileObj.id}"></div> <div class="file-item-meta" id="size-${fileObj.id}">${formatSize(fileObj.file.size)}</div>
            </div>
            <div class="file-item-status" id="status-${fileObj.id}">Ready</div>
            <div class="file-item-action" id="action-${fileObj.id}">
                <button type="button" class="remove-btn" onclick="removeFile('${fileObj.id}')">×</button>
            </div>
        `;
        const nameElement = item.querySelector(`#name-${fileObj.id}`);
        if (nameElement) {
            nameElement.textContent = fileObj.file.name; 
        }

        elements.fileList.appendChild(item);
    }

    window.removeFile = function(id) {
        const fileObj = fileQueue[id];
        if (fileObj && fileObj.jobId) {
            fetch(`/api/cleanup/${fileObj.jobId}`, { method: 'POST' }).catch(console.error);
            
            // --- REFRESH PROTECTION: Remove from storage if user manually deletes ---
            removeJobFromStorage(fileObj.jobId);
        }

        delete fileQueue[id];
        const el = document.getElementById(`file-${id}`);
        if (el) el.remove();

        if (Object.keys(fileQueue).length === 0) {
            resetAll(false);
        } else {
            updateConvertButton();
        }
    };

    function populateFormats(ext) {
        let formats;

        if (ext === 'pdf') {
            formats = [...OUTPUT_FORMATS.pdf]; // Copy array to avoid modifying original
        } else if (IMAGE_EXTENSIONS.has(ext)) {
            formats = [...OUTPUT_FORMATS.image];
        } else if (DOCUMENT_EXTENSIONS.has(ext)) {
            formats = [...OUTPUT_FORMATS.document];
        } else {
            formats = ['pdf'];
        }

        if (ext === 'pdf') {
            formats = formats.filter(f => f !== 'pdf');
        }

        if (ext === 'doc' || ext === 'docx') {
            formats = formats.filter(f => f !== 'docx');
        }
        // ------------------------------------------------

        elements.formatGrid.innerHTML = formats.map(fmt =>
            `<button type="button" class="format-btn" data-format="${fmt}">${fmt.toUpperCase()}</button>`
        ).join('');

        elements.formatGrid.querySelectorAll('.format-btn').forEach(btn => {
            btn.addEventListener('click', () => selectFormat(btn.dataset.format));
        });

        if (formats.length > 0) {
            selectFormat(formats[0]);
        }
    }

    function selectFormat(format) {
        selectedOutputFormat = format;

        elements.formatGrid.querySelectorAll('.format-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.format === format);
        });

        if (format === 'svg') {
            if (elements.vectorOptions) elements.vectorOptions.style.display = 'block';
            if (elements.standardOptions) elements.standardOptions.style.display = 'none';
        } else {
            if (elements.vectorOptions) elements.vectorOptions.style.display = 'none';
            if (elements.standardOptions) elements.standardOptions.style.display = 'grid';

            const showQuality = ['jpg', 'jpeg', 'webp'].includes(format);
            elements.qualityOption.style.display = showQuality ? 'flex' : 'none';
            const showBg = ['jpg', 'jpeg'].includes(format);
            elements.bgColorOption.style.display = showBg ? 'flex' : 'none';
        }

        updateConvertButton();
    }

    function updateConvertButton() {
        const count = Object.keys(fileQueue).length;

        // If in "Download" mode, don't reset logic yet unless cleared
        // Check if button has the 'completed' class which indicates download mode
        if (elements.convertBtn.classList.contains('completed')) {
            elements.convertBtn.disabled = false;
            return;
        }

        elements.convertBtn.disabled = count === 0 || !selectedOutputFormat;
        
        // Reset text logic only if NOT in liquid/progress mode
        if (!elements.convertBtn.classList.contains('btn-progress-mode')) {
            if (count > 1) {
                elements.btnText.textContent = `Convert ${count} Files`;
            } else if (count === 1) {
                elements.btnText.textContent = `Convert ${count} File`;
            } else {
                elements.btnText.textContent = `Convert All Files`;
            }
        }
    }

    // --- NEW: LIQUID NEON PROGRESS FUNCTIONS ---

    function startLiquidProgress() {
        const btn = elements.convertBtn;
        btn.classList.add('btn-progress-mode');
        // Inject Neon HTML Structure
        btn.innerHTML = `
            <div class="neon-bar" style="width: 5%"></div>
            <div class="progress-text-overlay">
                <span id="progressIcon">🚀</span> <span id="progressText">Initializing...</span>
            </div>
        `;
        btn.disabled = true; // Prevent clicks during progress
    }

    function updateLiquidProgress(percent, text) {
        const bar = elements.convertBtn.querySelector('.neon-bar');
        const txt = document.getElementById('progressText');
        const icon = document.getElementById('progressIcon');
        
        if (bar) bar.style.width = `${percent}%`;
        if (txt) txt.textContent = text;
        
        // Change icon based on stage
        if (percent > 30 && icon) icon.textContent = "⚡"; // Processing
        if (percent > 80 && icon) icon.textContent = "✨"; // Finalizing
    }

    function finishLiquidProgress(isMultiple) {
        const btn = elements.convertBtn;
        const bar = btn.querySelector('.neon-bar');
        const txt = document.getElementById('progressText');
        const icon = document.getElementById('progressIcon');

        if (bar) bar.style.width = '100%';
        btn.classList.add('completed'); // Activates green success state in CSS
        
        if (txt) txt.textContent = isMultiple ? "Download All (ZIP)" : "Download File";
        if (icon) icon.textContent = "✅";
        
        btn.disabled = false; // Re-enable for download click
        btn.style.cursor = "pointer";
    }

    // --- MAIN HANDLER WITH DOWNLOAD TRANSFORMATION ---
    async function handleBulkSubmit(e) {
        e.preventDefault();

        // 1. Check if button is in "Download" mode (using class check now)
        if (elements.convertBtn.classList.contains('completed')) {
            executeMainDownload();
            return;
        }

        // 2. Standard Conversion Logic
        if (Object.keys(fileQueue).length === 0 || !selectedOutputFormat) return;

        // --- NEW: START LIQUID ANIMATION ---
        showToast("Uploading your files... 📤", "processing");
        startLiquidProgress();
        
        isProcessing = true;

        const totalFiles = Object.keys(fileQueue).length;
        let processedCount = 0;

        // Create an array of promises but track progress
        const uploads = Object.values(fileQueue).map(async (fileObj) => {
            await uploadSingleFile(fileObj);
            
            // Increment progress after each file finishes
            processedCount++;
            const percent = Math.round((processedCount / totalFiles) * 100);
            
            // Update Bar Text dynamically based on stage
            let statusText = `Processing (${processedCount}/${totalFiles})`;
            if (percent < 30) statusText = `Uploading (${processedCount}/${totalFiles})`;
            else if (percent > 90) statusText = "Finalizing...";
            
            updateLiquidProgress(percent, statusText);
        });

        await Promise.allSettled(uploads);

        isProcessing = false;

        // 3. Transformation Logic (Finish)
        const completedCount = Object.values(fileQueue).filter(f => f.status === 'completed').length;

        if (completedCount > 0) {
            // Show Success Message
            showToast(`Conversion Completed! ✅`, "success");
            
            // Trigger Final Neon State
            finishLiquidProgress(completedCount > 1);
        } else {
            // If all failed, reset
            showToast("All conversions failed.", "error");
            resetAll(false); // Or maybe just reset button style? Better reset for safety.
        }
    }

    // --- NEW: EXECUTE DOWNLOAD (ZIP OR SINGLE) ---
    async function executeMainDownload() {
        const completedJobIds = Object.values(fileQueue)
            .filter(f => f.status === 'completed' && f.jobId)
            .map(f => f.jobId);

        if (completedJobIds.length === 0) return;

        // A) Single File - Direct Download
        if (completedJobIds.length === 1) {
            showToast("Downloading file... ✅", "success");
            // Find the download button in the file list and trigger it
            const fileObj = Object.values(fileQueue).find(f => f.jobId === completedJobIds[0]);
            const itemDownloadBtn = document.querySelector(`#action-${fileObj.id} .file-download-btn`);
            if (itemDownloadBtn) {
                itemDownloadBtn.click();
            }
            return;
        }

        // B) Multiple Files - ZIP Download
        // Update text manually since we are inside the custom button structure now
        const txt = document.getElementById('progressText');
        const originalText = txt ? txt.textContent : "Download All";
        if (txt) txt.textContent = "Zipping...";
        
        elements.convertBtn.disabled = true;
        showToast("Creating ZIP archive... 📦", "processing");

        try {
            const response = await fetch('/api/download-zip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_ids: completedJobIds })
            });

            const data = await response.json();

            if (data.success && data.download_url) {
                // Success: Redirect to download URL
                showToast("Download Started! ✅", "success");
                window.location.href = data.download_url;
            } else {
                throw new Error("Failed to generate download link");
            }

        } catch (error) {
            console.error(error);
            showToast("Failed to create ZIP", "error");
        } finally {
            if (txt) txt.textContent = originalText; // Revert text
            elements.convertBtn.disabled = false;
        }
    }

    async function uploadSingleFile(fileObj) {
        if (fileObj.status === 'completed') return;

        updateFileStatus(fileObj.id, 'Uploading...', 'processing');

        const formData = new FormData(elements.form);
        formData.set('file', fileObj.file);
        formData.append('output_format', selectedOutputFormat);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            if (response.status === 429) {
                updateFileStatus(fileObj.id, 'Too Fast! Wait...', 'error');
                throw new Error("Rate limit exceeded");
            }

            const data = await response.json();

            if (!response.ok) throw new Error(data.detail || 'Upload failed');

            // --- KEY FIX FOR BACKEND LIST RESPONSE ---
            // Backend sends 'jobs' list now, so we take the first one
            fileObj.jobId = data.jobs[0].job_id;
            // ----------------------------------------
            
            fileObj.status = 'processing';

            // --- REFRESH PROTECTION: Save Job to Storage ---
            saveJobToStorage(fileObj, selectedOutputFormat);

            await pollFile(fileObj);

        } catch (error) {
            const el = document.getElementById(`status-${fileObj.id}`);
            if (el && el.textContent !== 'Too Fast! Wait...') {
                updateFileStatus(fileObj.id, 'Failed', 'error');
            }
            console.error(error);
        }
    }

    function pollFile(fileObj) {
        return new Promise((resolve, reject) => {
            let polls = 0;

            const check = async () => {
                if (polls > CONFIG.maxPolls) {
                    updateFileStatus(fileObj.id, 'Timed Out', 'error');
                    resolve();
                    return;
                }
                polls++;

                try {
                    const res = await fetch(`/api/status/${fileObj.jobId}`);
                    const data = await res.json();

                    if (data.status === 'completed') {
                        fileObj.status = 'completed';
                        
                        // --- REFRESH PROTECTION: Clear from storage (Work Done) ---
                        removeJobFromStorage(fileObj.jobId);

                        const nameEl = document.getElementById(`name-${fileObj.id}`);
                        const sizeEl = document.getElementById(`size-${fileObj.id}`);

                        if (nameEl && data.output_filename) {
                            nameEl.textContent = data.output_filename;
                        }
                        if (sizeEl && data.output_size_formatted) {
                            sizeEl.textContent = data.output_size_formatted;
                            if (data.size_reduction_percent > 0) {
                                sizeEl.style.color = 'var(--color-success)';
                            }
                        }

                        showDownloadButton(fileObj);
                        resolve(); // Resolve promise so progress bar increments
                        
                    } else if (data.status === 'failed') {
                        fileObj.status = 'failed';
                        // --- REFRESH PROTECTION: Clear from storage (Failed) ---
                        removeJobFromStorage(fileObj.jobId);
                        
                        updateFileStatus(fileObj.id, 'Failed', 'error');
                        resolve(); // Resolve even if failed so flow continues
                    } else {
                        const progress = data.progress || 0;
                        updateFileStatus(fileObj.id, `${progress}%`, 'processing');
                        setTimeout(check, CONFIG.pollInterval);
                    }
                } catch (e) {
                    setTimeout(check, CONFIG.pollInterval * 2);
                }
            };

            check();
        });
    }

    function updateFileStatus(id, text, type) {
        const el = document.getElementById(`status-${id}`);
        if (el) {
            el.textContent = text;
            el.className = `file-item-status status-${type}`;
        }
    }

    async function showDownloadButton(fileObj) {
        try {
            const res = await fetch(`/api/download/${fileObj.jobId}`);
            const data = await res.json();

            const actionEl = document.getElementById(`action-${fileObj.id}`);
            const statusEl = document.getElementById(`status-${fileObj.id}`);

            if (statusEl) {
                statusEl.textContent = "Done";
                statusEl.className = "file-item-status status-success";
            }

            if (actionEl && data.success) {
                actionEl.innerHTML = `
                    <a href="${data.download_url}" download="${data.filename}" class="file-download-btn" onclick="scheduleCleanup('${fileObj.jobId}')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                    </a>
                `;
            }
        } catch (e) {
            console.error(e);
        }
    }

    window.scheduleCleanup = function(jobId) {
        setTimeout(() => {
            fetch(`/api/cleanup/${jobId}`, { method: 'POST' });
        }, 3000);
    };

    function resetAll(deleteFromServer = false) {
        if (deleteFromServer) {
            Object.values(fileQueue).forEach(file => {
                if (file.jobId) {
                    fetch(`/api/cleanup/${file.jobId}`, { method: 'POST' }).catch(err => console.log(err));
                    // Clean storage too
                    removeJobFromStorage(file.jobId);
                }
            });
        }
        
        // Also clear all storage to be safe
        localStorage.removeItem('app_active_jobs');

        fileQueue = {};
        isProcessing = false;

        elements.fileList.innerHTML = '';
        elements.fileListArea.style.display = 'none';
        elements.dropzone.style.display = 'block';
        elements.optionsSection.style.display = 'none';
        elements.fileInput.value = '';

        // --- RESET BUTTON TO ORIGINAL STATE ---
        elements.convertBtn.className = 'convert-btn'; // Remove custom classes
        elements.convertBtn.innerHTML = `
            <span class="btn-text">Convert All Files</span>
            <div class="btn-loader"></div>
        `;
        // Re-cache text element because HTML changed
        elements.btnText = document.querySelector('.btn-text');
        
        elements.convertBtn.disabled = true;
        elements.convertBtn.style.background = '';
        elements.convertBtn.style.borderColor = '';
    }

    // --- DEPRECATED: setGlobalLoading removed as Liquid Progress replaces it ---

    function getExtension(filename) {
        return filename.split('.').pop().toLowerCase();
    }

    function formatSize(bytes) {
        if (!bytes) return '0 B';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    // --- HELPER FUNCTIONS FOR REFRESH PROTECTION ---

    function saveJobToStorage(fileObj, format) {
        let jobs = JSON.parse(localStorage.getItem('app_active_jobs') || '[]');
        // Avoid duplicates
        if (!jobs.find(j => j.jobId === fileObj.jobId)) {
            jobs.push({
                internalId: fileObj.id,
                jobId: fileObj.jobId,
                fileName: fileObj.file.name,
                originalSize: fileObj.file.size,
                format: format
            });
            localStorage.setItem('app_active_jobs', JSON.stringify(jobs));
        }
    }

    function removeJobFromStorage(jobId) {
        let jobs = JSON.parse(localStorage.getItem('app_active_jobs') || '[]');
        jobs = jobs.filter(j => j.jobId !== jobId);
        if (jobs.length === 0) {
            localStorage.removeItem('app_active_jobs');
        } else {
            localStorage.setItem('app_active_jobs', JSON.stringify(jobs));
        }
    }

    function restoreActiveJobs() {
        const stored = localStorage.getItem('app_active_jobs');
        if (!stored) return;

        try {
            const jobs = JSON.parse(stored);
            if (!Array.isArray(jobs) || jobs.length === 0) return;

            // Restore UI state
            elements.dropzone.style.display = 'none';
            elements.fileListArea.style.display = 'block';
            elements.optionsSection.style.display = 'flex';
            
            jobs.forEach(job => {
                // Reconstruct a "Dummy" file object
                // Note: We set type to 'application/restored' to avoid triggering createObjectURL
                const fileObj = {
                    id: job.internalId,
                    file: { 
                        name: job.fileName, 
                        size: job.originalSize || 0, 
                        type: 'application/restored' // Safe dummy type
                    },
                    jobId: job.jobId,
                    status: 'processing',
                    progress: 0
                };
                
                fileQueue[job.internalId] = fileObj;
                selectedOutputFormat = job.format; // Restore selected format

                // Add to UI (Icon will show extension, not image preview)
                addFileToList(fileObj);
                updateFileStatus(fileObj.id, 'Resuming...', 'processing');

                // Resume Polling immediately
                pollFile(fileObj);
            });
            
            // Set global processing state (Visual only)
            // Ideally we should startLiquidProgress here too if restoring, 
            // but for simplicity we keep basic restoration until new upload.
            isProcessing = true;

        } catch (e) {
            console.error("Failed to restore jobs:", e);
            localStorage.removeItem('app_active_jobs');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // --- TOAST FUNCTION ---
    function showToast(message, type = 'success') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        let icon = type === 'success'
            ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';

        // Use Spinner for Processing Toast
        if (type === 'processing') {
             icon = '<svg class="spinner" style="width:20px;height:20px;" viewBox="0 0 24 24"><circle class="spinner-circle" cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="3"></circle></svg>';
        }

        toast.innerHTML = `${icon}<span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // --- NEW: Browser Close Cleanup (Send Beacon) ---
    window.addEventListener('beforeunload', function() {
        // Only run if there are active files
        if (Object.keys(fileQueue).length > 0) {
            const firstJob = Object.values(fileQueue)[0];
            if (firstJob && firstJob.jobId) {
                const data = new FormData();
                data.append('job_id', firstJob.jobId);
                // navigator.sendBeacon(`/api/cleanup/${firstJob.jobId}`); 
            }
        }
    });

    // --- FAQ Animation Logic ---
    function initFAQ() {
        const questions = document.querySelectorAll('.faq-question');
        questions.forEach(question => {
            question.addEventListener('click', (e) => {
                e.preventDefault();
                const item = question.parentElement;

                document.querySelectorAll('.faq-item').forEach(otherItem => {
                    if (otherItem !== item) {
                        otherItem.classList.remove('open');
                    }
                });

                item.classList.toggle('open');
            });
        });
    }

    // Run FAQ on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFAQ);
    } else {
        initFAQ();
    }

})();
