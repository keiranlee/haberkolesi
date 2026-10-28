(function () {
  'use strict';

  document.querySelectorAll('[data-copy-target]').forEach(function (button) {
    button.addEventListener('click', async function () {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.value || target.textContent);
        button.textContent = 'Kopyalandı';
      } catch (error) {
        target.focus();
        target.select();
        button.textContent = 'Metin seçildi · Ctrl/Cmd+C ile kopyala';
      }
    });
  });

  const forms = document.querySelectorAll('.regenerate-form, .generate-form, .score-form');
  if (!forms.length) return;

  forms.forEach(function (form) {
    const button = form.querySelector('button[type="submit"]');
    const originalButtonHtml = button ? button.innerHTML : '';
    let statusMessage = form.parentElement.querySelector('.action-status-helper');
    if (!statusMessage) {
      statusMessage = document.createElement('p');
      statusMessage.className = 'action-helper action-status-helper';
      statusMessage.setAttribute('role', 'status');
      statusMessage.setAttribute('aria-live', 'polite');
      form.parentElement.appendChild(statusMessage);
    }

    const isScore = form.classList.contains('score-form');

    function setRunning() {
      if (button) {
        button.disabled = true;
        button.innerHTML = isScore
          ? '<span class="spinner" aria-hidden="true"></span>AI puanlıyor…'
          : '<span class="spinner" aria-hidden="true"></span>Yeni metin hazırlanıyor…';
      }
      statusMessage.textContent = isScore
        ? 'Seçili AI haber analizi ve puanlamasını yapıyor. Lütfen bekle…'
        : 'Sosyal metinler, ayrıntılı blog ve görsel hazırlanıyor. Sonuç hazır olduğunda sayfa otomatik güncellenecek.';
    }

    function setFailed(message) {
      if (button) {
        button.disabled = false;
        button.innerHTML = originalButtonHtml;
      }
      statusMessage.textContent = message || 'İşlem tamamlanamadı. Lütfen tekrar dene.';
    }

    async function pollJob(jobId) {
      for (let attempt = 0; attempt < 240; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const response = await fetch(`/ai-jobs/${jobId}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (!response.ok) throw new Error('İş durumu alınamadı.');
        const job = await response.json();
        if (job.state === 'completed') {
          statusMessage.textContent = isScore
            ? 'Puanlama tamamlandı! Sayfa güncelleniyor…'
            : 'Metin ve görsel hazır! Sayfa güncelleniyor…';
          window.location.reload();
          return;
        }
        if (job.state === 'failed') {
          setFailed(job.error || 'İşlem gerçekleştirilemedi.');
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
        if (!response.ok) throw new Error('İşlem başlatılamadı.');
        const job = await response.json();
        await pollJob(job.job_id);
      } catch (error) {
        setFailed(error.message);
      }
    });
  });
})();
