document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const taskInput = document.getElementById('task-input');
    const headlessToggle = document.getElementById('headless-toggle');
    const maxStepsInput = document.getElementById('max-steps');
    const startBtn = document.getElementById('start-btn');
    const chatForm = document.getElementById('chat-form');
    const chatMessages = document.getElementById('chat-messages');
    const globalStatus = document.getElementById('global-status');
    const liveUrlInput = document.getElementById('live-url');

    const screenshotImg = document.getElementById('screenshot-img');
    const screenshotPlaceholder = document.getElementById('screenshot-placeholder');

    const confirmationOverlay = document.getElementById('confirmation-overlay');
    const confirmationMessage = document.getElementById('confirmation-message');
    const confirmationScreenshot = document.getElementById('confirmation-screenshot');
    const btnConfirm = document.getElementById('btn-confirm');
    const btnCancel = document.getElementById('btn-cancel');

    const summaryOverlay = document.getElementById('summary-overlay');
    const summaryOutcome = document.getElementById('summary-outcome');
    const summarySteps = document.getElementById('summary-steps');
    const summaryText = document.getElementById('summary-text');
    const btnCloseSummary = document.getElementById('btn-close-summary');

    // State
    let currentSessionId = null;
    let ws = null;
    let currentStepCount = 0;

    // Global suggestion pill helper
    window.fillTask = (text) => {
        taskInput.value = text;
        taskInput.focus();
    };

    // Auto-resize textarea
    taskInput.addEventListener('input', () => {
        taskInput.style.height = 'auto';
        taskInput.style.height = (taskInput.scrollHeight) + 'px';
    });

    // Handle form submit
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        startTask();
    });

    taskInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            startTask();
        }
    });

    // Start Task
    async function startTask() {
        const task = taskInput.value.trim();
        if (!task || startBtn.disabled) return;

        const headless = headlessToggle.checked;
        const maxSteps = parseInt(maxStepsInput.value, 10) || 25;

        // Add User Bubble to Chat
        addUserChatBubble(task);
        taskInput.value = '';
        taskInput.style.height = 'auto';

        // UI State
        startBtn.disabled = true;
        startBtn.innerHTML = `<span>Running...</span>`;
        updateStatus('active', 'Running Task');
        currentStepCount = 0;

        try {
            const response = await fetch('/api/task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task, headless, max_steps: maxSteps })
            });

            if (!response.ok) {
                throw new Error(`Server status ${response.status}`);
            }

            const data = await response.json();
            currentSessionId = data.session_id;

            connectWebSocket(currentSessionId);

        } catch (error) {
            console.error('Task launch error:', error);
            addAgentChatBubble(`⚠️ System Error: ${error.message}`);
            resetUI();
        }
    }

    // WebSocket Manager
    function connectWebSocket(sessionId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`;
        
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket stream active');
        };

        ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                handleWsMessage(message);
            } catch (e) {
                console.error('Failed to parse WS data:', e);
            }
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };

        ws.onclose = () => {
            if (globalStatus.classList.contains('active')) {
                updateStatus('inactive', 'Completed');
                resetUI();
            }
        };
    }

    // Handle WebSocket Stream Events
    function handleWsMessage(message) {
        const { type, data } = message;
        if (!data) return;

        switch (type) {
            case 'step_update':
                currentStepCount = data.step_number || currentStepCount;
                
                // Add step update card to chat stream
                addStepToChat(data);

                // Update Live View Screenshot & URL
                if (data.screenshot) {
                    updateLiveViewport(data.screenshot);
                }

                if (data.action && data.action.target && data.action.target.startsWith('http')) {
                    liveUrlInput.value = data.action.target;
                }

                if (data.status === 'awaiting_confirmation') {
                    showConfirmation({
                        message: data.message,
                        screenshot: data.screenshot
                    });
                }
                break;

            case 'confirmation_needed':
                showConfirmation(data);
                break;

            case 'task_complete':
                showSummary(data.summary || {});
                if (ws) ws.close();
                break;

            case 'error':
                addAgentChatBubble(`<i class="fa-solid fa-triangle-exclamation"></i> Execution Error: ${data.message || 'An error occurred.'}`);
                resetUI();
                break;
        }
    }

    // Add User Chat Bubble
    function addUserChatBubble(text) {
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble user-bubble';
        bubble.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-user"></i></div>
            <div class="bubble-content">${escapeHtml(text)}</div>
        `;
        chatMessages.appendChild(bubble);
        scrollChatToBottom();
    }

    // Add Agent Chat Bubble
    function addAgentChatBubble(text) {
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble agent-bubble';
        bubble.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="bubble-content">
                <div class="agent-name">Aegis Agent</div>
                <p>${text}</p>
            </div>
        `;
        chatMessages.appendChild(bubble);
        scrollChatToBottom();
    }

    // Add Step reasoning / action card to Chat Stream
    function addStepToChat(data) {
        const stepNum = data.step_number || 1;
        const status = data.status || 'info';
        const action = data.action;
        const actionType = action ? action.action : 'Action';
        const message = data.message || '';

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble agent-bubble';
        
        let tagClass = 'deciding';
        let iconHtml = '<i class="fa-solid fa-brain"></i>';
        let title = `Step ${stepNum} — AI Reasoning`;

        if (status === 'executed') {
            tagClass = 'executed';
            iconHtml = '<i class="fa-solid fa-bolt"></i>';
            title = `Step ${stepNum} — Executed: ${actionType.toUpperCase()}`;
        } else if (status === 'error') {
            tagClass = 'error';
            iconHtml = '<i class="fa-solid fa-triangle-exclamation"></i>';
            title = `Step ${stepNum} — Action Error`;
        }

        bubble.innerHTML = `
            <div class="avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="bubble-content">
                <div class="chat-step-card">
                    <div class="step-card-header">
                        <strong>${iconHtml} ${escapeHtml(title)}</strong>
                        <span class="step-tag ${tagClass}">${escapeHtml(status)}</span>
                    </div>
                    <div class="step-reasoning">${escapeHtml(message)}</div>
                </div>
            </div>
        `;
        chatMessages.appendChild(bubble);
        scrollChatToBottom();
    }

    // Live View Screenshot update
    function updateLiveViewport(base64Data) {
        if (!base64Data) return;
        const mimeType = base64Data.startsWith('iVBORw') ? 'image/png' : 'image/jpeg';
        const srcUrl = base64Data.startsWith('data:') ? base64Data : `data:${mimeType};base64,${base64Data}`;
        screenshotImg.src = srcUrl;
        screenshotImg.style.display = 'block';
        screenshotPlaceholder.style.display = 'none';
    }

    function scrollChatToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function updateStatus(state, text) {
        globalStatus.className = `status-badge ${state}`;
        globalStatus.querySelector('.status-text').textContent = text;
    }

    function resetUI() {
        startBtn.disabled = false;
        startBtn.innerHTML = `<span>Send Task</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;
        updateStatus('inactive', 'Idle');
    }

    // Confirmation Modal
    function showConfirmation(data) {
        confirmationMessage.textContent = data.message || 'Action requires confirmation.';
        if (data.screenshot) {
            updateLiveViewport(data.screenshot);
            confirmationScreenshot.src = screenshotImg.src;
        }
        confirmationOverlay.classList.remove('hidden');
    }

    function hideConfirmation() {
        confirmationOverlay.classList.add('hidden');
    }

    btnConfirm.addEventListener('click', () => {
        hideConfirmation();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'confirmation_response', data: { confirmed: true } }));
        }
    });

    btnCancel.addEventListener('click', () => {
        hideConfirmation();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'confirmation_response', data: { confirmed: false } }));
        }
    });

    // Summary Modal
    function showSummary(summary) {
        const status = summary.status || 'completed';
        summaryOutcome.textContent = status.toUpperCase();
        summaryOutcome.style.color = (status === 'completed' || status === 'complete') ? 'var(--accent-emerald)' : 'var(--error)';
        summarySteps.textContent = summary.step_count || currentStepCount;
        summaryText.textContent = summary.task || summary.error || 'Task completed successfully.';

        addAgentChatBubble(`🎉 Task finished! Outcome: ${status.toUpperCase()}. Total steps taken: ${summary.step_count || currentStepCount}.`);
        summaryOverlay.classList.remove('hidden');
        resetUI();
    }

    btnCloseSummary.addEventListener('click', () => {
        summaryOverlay.classList.add('hidden');
    });

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }
});
