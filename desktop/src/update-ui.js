// Shared update banner for the two desktop apps.
(() => {
  const api = window.ffu || window.vees;
  const byId = id => document.getElementById(id);
  const banner = byId('update-banner');
  const checkButton = byId('check-updates');
  const openButton = byId('update-open');
  const dismissButton = byId('update-dismiss');
  const originalLabel = checkButton.textContent;
  let latest = null;

  function render(result, manual) {
    latest = result;
    if (!manual && (result.status !== 'available' || result.dismissed)) {
      banner.classList.add('hidden');
      return;
    }
    banner.className = `update-banner ${result.status === 'available' ? '' : result.status === 'error' ? 'error' : 'info'}`;
    openButton.classList.toggle('hidden', result.status !== 'available');
    if (result.status === 'available') {
      byId('update-title').textContent = `New VE-ES source available · ${result.latestCommit.slice(0, 7)}`;
      byId('update-message').textContent = `${result.title || 'The upstream repository has changed.'} A rebuilt desktop package is needed to use this code.`;
    } else if (result.status === 'current') {
      byId('update-title').textContent = 'VE-ES source is up to date';
      byId('update-message').textContent = `This app includes the current upstream commit ${result.latestCommit.slice(0, 7)}.`;
    } else {
      byId('update-title').textContent = 'Could not check for updates';
      byId('update-message').textContent = `${result.message || 'Check your internet connection and try again.'}`;
    }
  }

  checkButton.addEventListener('click', async () => {
    checkButton.disabled = true;
    checkButton.textContent = 'Checking…';
    try { render(await api.checkUpdates(), true); }
    catch (error) { render({status: 'error', message: error.message}, true); }
    finally {checkButton.disabled = false; checkButton.textContent = originalLabel;}
  });
  openButton.addEventListener('click', async () => {
    if (latest?.status === 'available') await api.openUpdate();
  });
  dismissButton.addEventListener('click', async () => {
    if (latest?.status === 'available') await api.dismissUpdate(latest.latestCommit);
    banner.classList.add('hidden');
  });
  api.on('update-status', result => render(result, false));
  api.checkUpdates().then(result => render(result, false)).catch(() => {});
})();
