(function () {
  let pollTimer = null;
  let isUpdating = false;

  function getPollInterval(doc) {
    const liveEl = doc.getElementById('live-state');
    const activeInDom = doc.querySelectorAll('.score-in-progress, .state-running').length;
    if (!liveEl && activeInDom === 0) return 8000;
    const batchState = liveEl ? (liveEl.dataset.batchState || 'none') : 'none';
    const runningJobs = parseInt(liveEl ? (liveEl.dataset.runningJobs || '0') : '0', 10);
    const pendingJobs = parseInt(liveEl ? (liveEl.dataset.pendingJobs || '0') : '0', 10);

    // If batch is running or jobs are active/pending or spinner elements exist, poll fast (1.5 seconds)
    if (batchState === 'running' || runningJobs > 0 || pendingJobs > 0 || activeInDom > 0) {
      return 1500;
    }
    // Idle interval
    return 8000;
  }

  function applyUpdate(newHtml) {
    const parser = new DOMParser();
    const newDoc = parser.parseFromString(newHtml, 'text/html');

    // 1. Update collection status banner
    const currentStatus = document.querySelector('.collection-status');
    const newStatus = newDoc.querySelector('.collection-status');
    const overview = document.getElementById('overview');

    if (newStatus && currentStatus) {
      currentStatus.outerHTML = newStatus.outerHTML;
    } else if (newStatus && !currentStatus && overview) {
      overview.insertAdjacentElement('afterend', newStatus);
    } else if (!newStatus && currentStatus) {
      currentStatus.remove();
    }

    // 2. Update Collect button in #overview
    const currentCollectBtn = document.querySelector('.button-collect');
    const newCollectBtn = newDoc.querySelector('.button-collect');
    if (currentCollectBtn && newCollectBtn) {
      currentCollectBtn.outerHTML = newCollectBtn.outerHTML;
    }

    // 3. Update Metrics Grid
    const currentMetrics = document.querySelector('.metrics-grid');
    const newMetrics = newDoc.querySelector('.metrics-grid');
    if (currentMetrics && newMetrics) {
      currentMetrics.innerHTML = newMetrics.innerHTML;
    }

    // 4. Update Queue Stats & Rate Badge
    const currentQueue = document.querySelector('.queue-stats');
    const newQueue = newDoc.querySelector('.queue-stats');
    if (currentQueue && newQueue) {
      currentQueue.innerHTML = newQueue.innerHTML;
    }

    const currentRate = document.querySelector('.rate-badge');
    const newRate = newDoc.querySelector('.rate-badge');
    if (currentRate && newRate) {
      currentRate.innerHTML = newRate.innerHTML;
    }

    // 5. Update News Count in heading
    const currentCount = document.querySelector('#news-title span');
    const newCount = newDoc.querySelector('#news-title span');
    if (currentCount && newCount) {
      currentCount.textContent = newCount.textContent;
    }

    // 6. Update News Container (Table or Empty state)
    const currentNews = document.getElementById('news-container');
    const newNews = newDoc.getElementById('news-container');
    if (currentNews && newNews) {
      if (currentNews.innerHTML !== newNews.innerHTML) {
        currentNews.innerHTML = newNews.innerHTML;
      }
    }

    // 7. Update Live State metadata
    const currentLiveState = document.getElementById('live-state');
    const newLiveState = newDoc.getElementById('live-state');
    if (currentLiveState && newLiveState) {
      currentLiveState.dataset.batchState = newLiveState.dataset.batchState || 'none';
      currentLiveState.dataset.runningJobs = newLiveState.dataset.runningJobs || '0';
      currentLiveState.dataset.pendingJobs = newLiveState.dataset.pendingJobs || '0';
      currentLiveState.dataset.totalRecords = newLiveState.dataset.totalRecords || '0';
    }

    // Rebind form listener if button/form was refreshed
    bindCollectForm();
    bindScoreForms();

    return getPollInterval(newDoc);
  }

  async function fetchUpdate() {
    if (isUpdating) return;
    isUpdating = true;
    try {
      const response = await fetch(window.location.href, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        cache: 'no-store'
      });
      if (response.ok) {
        const html = await response.text();
        const nextInterval = applyUpdate(html);
        scheduleNext(nextInterval);
      } else {
        scheduleNext(6000);
      }
    } catch (err) {
      scheduleNext(6000);
    } finally {
      isUpdating = false;
    }
  }

  function scheduleNext(ms) {
    if (pollTimer) clearTimeout(pollTimer);
    if (!document.hidden) {
      pollTimer = setTimeout(fetchUpdate, ms);
    }
  }

  function bindCollectForm() {
    const form = document.querySelector('.collect-form');
    if (!form || form.dataset.ajaxBound) return;
    form.dataset.ajaxBound = 'true';

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const btn = form.querySelector('.button-collect');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>Haberler çekiliyor…';
      }

      // If no status banner exists yet, create an immediate active one
      let statusBanner = document.querySelector('.collection-status');
      if (!statusBanner) {
        const overview = document.getElementById('overview');
        if (overview) {
          const tempStatus = document.createElement('section');
          tempStatus.className = 'collection-status status-running';
          tempStatus.setAttribute('aria-live', 'polite');
          tempStatus.innerHTML = `
            <span class="status-symbol"><span class="spinner"></span></span>
            <div>
              <strong>Kaynaklar taranıyor</strong>
              <small>Haber havuzu güncelleniyor, yeni adaylar anlık olarak listelenecek…</small>
            </div>
            <span class="batch-id">Canlı</span>
          `;
          overview.insertAdjacentElement('afterend', tempStatus);
        }
      }

      try {
        const formData = new FormData(form);
        const res = await fetch(form.action, {
          method: 'POST',
          body: formData,
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (res.ok) {
          const html = await res.text();
          applyUpdate(html);
        }
      } catch (err) {
        console.error('Haber çekme hatası:', err);
      }

      // Schedule fast poll in 1 second
      scheduleNext(1000);
    });
  }

  function bindScoreForms() {
    document.querySelectorAll('.score-form-inline').forEach(function (form) {
      if (form.dataset.bound) return;
      form.dataset.bound = 'true';
      form.addEventListener('submit', async function (event) {
        event.preventDefault();
        const btn = form.querySelector('button');
        if (btn) {
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner" aria-hidden="true" style="width:10px;height:10px;border-width:1.5px;margin-right:4px;"></span>Puanlanıyor…';
        }
        try {
          const res = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
          });
          if (res.ok) {
            scheduleNext(1500);
          }
        } catch (err) {
          console.error('Puanlama hatası:', err);
        }
      });
    });
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) {
      fetchUpdate();
    }
  });

  // Start
  bindCollectForm();
  bindScoreForms();
  const initialInterval = getPollInterval(document);
  scheduleNext(initialInterval);
})();
