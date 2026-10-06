const https = require('node:https');

const API_URL = 'https://api.github.com/repos/Foxiary/VE-ES/commits?per_page=1';

function latestFromResponse(items, bundledCommit) {
  const commit = Array.isArray(items) ? items[0] : null;
  const sha = commit?.sha;
  if (typeof sha !== 'string' || !/^[0-9a-f]{40}$/.test(sha)) {
    throw new Error('GitHub returned an invalid commit.');
  }
  return {
    status: sha === bundledCommit ? 'current' : 'available',
    bundledCommit,
    latestCommit: sha,
    title: String(commit.commit?.message || '').split(/\r?\n/)[0].slice(0, 160),
    url: `https://github.com/Foxiary/VE-ES/commit/${sha}`,
    checkedAt: new Date().toISOString()
  };
}

function fetchLatest() {
  return new Promise((resolve, reject) => {
    const request = https.get(API_URL, {
      headers: {'Accept': 'application/vnd.github+json', 'User-Agent': 'VE-ES-Desktop-Update-Check'}
    }, response => {
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`GitHub returned HTTP ${response.statusCode}.`));
        return;
      }
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 256_000) request.destroy(new Error('Update response is too large.'));
      });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch { reject(new Error('GitHub returned unreadable update data.')); }
      });
      response.on('error', reject);
    });
    request.setTimeout(10_000, () => request.destroy(new Error('Update check timed out.')));
    request.on('error', reject);
  });
}

async function checkForUpdate(bundledCommit, requestLatest = fetchLatest) {
  return latestFromResponse(await requestLatest(), bundledCommit);
}

module.exports = {checkForUpdate, latestFromResponse};
