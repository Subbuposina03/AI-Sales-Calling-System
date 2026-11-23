// AI Sales Calling Agent - Frontend Controller
document.addEventListener('DOMContentLoaded', () => {
  const callForm = document.getElementById('callForm');
  const callBtn = document.getElementById('callBtn');
  const btnText = callBtn.querySelector('.btn-text');
  const btnSpinner = callBtn.querySelector('.btn-spinner');
  const btnIcon = callBtn.querySelector('.btn-icon');
  
  const countryCodeSelect = document.getElementById('countryCode');
  const phoneInput = document.getElementById('phoneNumber');
  const fullNumberPreview = document.getElementById('fullNumberPreview');
  const consentCheckbox = document.getElementById('consentCheckbox');
  
  const statusPanel = document.getElementById('statusPanel');
  const callStatusBadge = document.getElementById('callStatusBadge');
  
  const step1 = document.getElementById('step1');
  const step2 = document.getElementById('step2');
  const step3 = document.getElementById('step3');
  const step4 = document.getElementById('step4');
  const line1 = document.getElementById('line1');
  const line2 = document.getElementById('line2');
  const line3 = document.getElementById('line3');
  
  const alertBox = document.getElementById('alertBox');
  const alertTitle = document.getElementById('alertTitle');
  const alertMessage = document.getElementById('alertMessage');
  const alertCallSid = document.getElementById('alertCallSid');

  let pollingInterval = null;

  // Initialize default phone if present
  let initial = phoneInput.value.trim();
  if (initial) {
    for (const opt of countryCodeSelect.options) {
      if (initial.startsWith(opt.value)) {
        countryCodeSelect.value = opt.value;
        phoneInput.value = initial.substring(opt.value.length).trim();
        break;
      }
    }
  }

  // Format and update preview of destination number
  function updatePreview() {
    const code = countryCodeSelect.value.trim();
    let num = phoneInput.value.replace(/[\s\-\(\)]/g, '');
    if (num.startsWith('0')) {
      num = num.substring(1);
    }
    const full = num ? `${code} ${num}` : code;
    fullNumberPreview.textContent = full;
  }

  countryCodeSelect.addEventListener('change', updatePreview);
  phoneInput.addEventListener('input', updatePreview);
  updatePreview();

  // Reset visual steps
  function resetSteps() {
    [step1, step2, step3, step4].forEach(s => {
      s.className = 'step-item';
    });
    [line1, line2, line3].forEach(l => {
      l.className = 'step-line';
    });
  }

  // Set visual step active / completed
  function setStepState(activeStep) {
    resetSteps();
    if (activeStep >= 1) {
      step1.classList.add(activeStep > 1 ? 'step-complete' : 'step-active');
    }
    if (activeStep >= 2) {
      line1.classList.add(activeStep > 2 ? 'line-complete' : 'line-active');
      step2.classList.add(activeStep > 2 ? 'step-complete' : 'step-active');
    }
    if (activeStep >= 3) {
      line2.classList.add(activeStep > 3 ? 'line-complete' : 'line-active');
      step3.classList.add(activeStep > 3 ? 'step-complete' : 'step-active');
    }
    if (activeStep >= 4) {
      line3.classList.add(activeStep > 4 ? 'line-complete' : 'line-active');
      step4.classList.add('step-active');
    }
  }

  // Set status badge state
  function setStatusBadge(statusText, badgeClass) {
    callStatusBadge.textContent = statusText;
    callStatusBadge.className = `status-badge ${badgeClass}`;
  }

  // Show Alert
  function showAlert(type, title, message, callSid = null) {
    alertBox.style.display = 'flex';
    alertBox.className = `alert-box alert-${type}`;
    alertTitle.textContent = title;
    alertMessage.textContent = message;

    if (callSid) {
      alertCallSid.style.display = 'inline-block';
      alertCallSid.textContent = `Call SID: ${callSid}`;
    } else {
      alertCallSid.style.display = 'none';
    }
  }

  // Set loading state on button
  function setLoading(loading) {
    callBtn.disabled = loading;
    phoneInput.disabled = loading;
    countryCodeSelect.disabled = loading;
    consentCheckbox.disabled = loading;

    if (loading) {
      btnText.textContent = 'Initiating Call...';
      btnSpinner.style.display = 'inline-block';
      btnIcon.style.display = 'none';
    } else {
      btnText.textContent = 'Call Me Now';
      btnSpinner.style.display = 'none';
      btnIcon.style.display = 'inline-block';
    }
  }

  // Poll Twilio for live status
  function startPollingStatus(callSid) {
    if (pollingInterval) clearInterval(pollingInterval);

    let attempts = 0;
    pollingInterval = setInterval(async () => {
      attempts++;
      if (attempts > 30) { // Stop polling after 1.5 minutes
        clearInterval(pollingInterval);
        return;
      }

      try {
        const res = await fetch(`/call_status/${encodeURIComponent(callSid)}`);
        if (!res.ok) return;
        const data = await res.json();
        const status = (data.status || '').toLowerCase();

        if (status === 'queued') {
          setStatusBadge('Queued', 'badge-initiating');
          setStepState(2);
        } else if (status === 'ringing') {
          setStatusBadge('Phone Ringing...', 'badge-ringing');
          setStepState(3);
        } else if (status === 'in-progress') {
          setStatusBadge('Conversation Active', 'badge-in-progress');
          setStepState(4);
        } else if (status === 'completed') {
          setStatusBadge('Call Completed', 'badge-completed');
          setStepState(4);
          step4.classList.add('step-complete');
          clearInterval(pollingInterval);
        } else if (['failed', 'busy', 'no-answer', 'canceled'].includes(status)) {
          setStatusBadge(`Ended (${status})`, 'badge-failed');
          clearInterval(pollingInterval);
        }
      } catch (err) {
        console.warn('Status poll failed:', err);
      }
    }, 3000);
  }

  // Form Submission Handler
  callForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    // 1. Consent verification
    if (!consentCheckbox.checked) {
      statusPanel.style.display = 'block';
      showAlert('error', 'Consent Required', 'Please check the consent box to confirm you agree to receive an automated AI demonstration call.');
      return;
    }

    // 2. Format Phone Number into E.164
    const countryCode = countryCodeSelect.value.trim();
    let rawNumber = phoneInput.value.replace(/[\s\-\(\)]/g, '');
    if (rawNumber.startsWith('0')) rawNumber = rawNumber.substring(1);

    if (!rawNumber || rawNumber.length < 7) {
      statusPanel.style.display = 'block';
      showAlert('error', 'Invalid Number', 'Please enter a valid mobile number with at least 8 digits.');
      phoneInput.focus();
      return;
    }

    const fullPhoneNumber = `${countryCode}${rawNumber}`;

    // 3. UI State updates
    statusPanel.style.display = 'block';
    alertBox.style.display = 'none';
    setLoading(true);
    setStepState(1);
    setStatusBadge('Validating...', 'badge-initiating');

    try {
      // Small pause for visual feedback
      await new Promise(r => setTimeout(r, 400));
      setStepState(2);
      setStatusBadge('Dispatching Call...', 'badge-initiating');

      const response = await fetch('/trigger_call', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          phone: fullPhoneNumber,
          consent: true
        })
      });

      const result = await response.json();

      if (response.ok && result.success) {
        setStepState(3);
        setStatusBadge('Call Dispatched', 'badge-ringing');

        const isSimulated = result.status === 'simulated';
        const successTitle = isSimulated ? 'Simulation Successful' : 'Call Initiated!';
        const successMsg = isSimulated 
          ? `Simulation mode is active. Webhook was invoked without dialing Twilio carrier.` 
          : `Twilio has placed the call to ${result.phone}. Pick up your phone to speak with Ajay, our AI Sales Counselor!`;

        showAlert('success', successTitle, successMsg, result.call_sid);

        if (result.call_sid) {
          startPollingStatus(result.call_sid);
        }
      } else {
        setStatusBadge('Call Failed', 'badge-failed');
        resetSteps();
        const errMessage = result.error || 'Failed to initiate call. Please try again.';
        showAlert('error', 'Call Dispatch Error', errMessage);
      }
    } catch (networkErr) {
      setStatusBadge('Network Error', 'badge-failed');
      resetSteps();
      showAlert('error', 'Connection Failed', 'Could not communicate with backend server. Please verify your connection.');
    } finally {
      setLoading(false);
    }
  });
});
