(function () {
  'use strict';

  const form = document.querySelector('.regenerate-form');
  if (!form) return;

  const button = form.querySelector('button[type="submit"]');
  const originalButtonHtml = button ? button.innerHTML : '';
  let statusMessage = form.parentElement.querySelector('.regeneration-status');
  if (!statusMessage) {
    statusMessage = document.createElement('p');
    statusMessage.className = 'action-helper regeneration-status';
    statusMessage.setAttribute('role', 'status');
    statusMessage.setAttribute('aria-live', 'polite');
    form.parentElement.appendChild(statusMessage);
  }

  function setRunning() {
    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner" aria-hidden="true"></span>Yeni metin hazırlanıyor…';
    }
    statusMessage.textContent = 'Gemini yeni metni ve görseli hazırlıyor. Bu sayfa sonuç hazır olduğunda otomatik güncellenecek.';
  }

  function setFailed(message) {
    if (button) {
      button.disabled = false;
      button.innerHTML = originalButtonHtml;
    }
    statusMessage.textContent = message || 'Yeni metin üretilemedi. Lütfen tekrar dene.';
  }

  async function pollJob(jobId) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const response = await fetch(`/ai-jobs/${jobId}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!response.ok) throw new Error('İş durumu alınamadı.');
      const job = await response.json();
      if (job.state === 'completed') {
        statusMessage.textContent = 'Yeni metin hazır. Sayfa güncelleniyor…';
        window.location.reload();
        return;
      }
      if (job.state === 'failed') {
        setFailed(job.error || 'Yeni metin üretilemedi.');
        return;
      }
    }
    setFailed('İşlem beklenenden uzun sürdü. Sayfayı yenileyerek durumu kontrol et.');
  }

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    setRunning();
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!response.ok) throw new Error('Yeniden üretme başlatılamadı.');
      const job = await response.json();
      await pollJob(job.job_id);
    } catch (error) {
      setFailed(error.message);
    }
  });
})();
