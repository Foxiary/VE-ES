const {app, BrowserWindow, dialog, ipcMain, shell, Notification} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const {tools} = require('./catalog');
const previousHashes = require('./engine-update.json');
const {checkForUpdate} = require('./update-check');

let window;
let currentRun = null;
let settings;
let lastUpdate = null;
let updateRequest = null;
const SOURCE_COMMIT = '019ccceaf78e4862519e4164e9e0d317da5d745b';
const byId = new Map(tools.map(tool => [tool.id, tool]));

function settingsPath() { return path.join(app.getPath('userData'), 'settings.json'); }
function loadSettings() {
  try { settings = JSON.parse(fs.readFileSync(settingsPath(), 'utf8')); }
  catch { settings = {}; }
  settings.workspace ||= path.join(app.getPath('userData'), 'workspace');
  settings.python ||= process.platform === 'win32' ? 'py' : 'python3';
  settings.history ||= [];
  settings.values ||= {};
}
function saveSettings() {
  fs.mkdirSync(path.dirname(settingsPath()), {recursive: true});
  fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2));
}
function enginePath() { return path.resolve(__dirname, '..', 'engine'); }
function copyMissing(source, target, relative) {
  const stat = fs.statSync(source);
  if (stat.isDirectory()) {
    fs.mkdirSync(target, {recursive: true});
    for (const name of fs.readdirSync(source)) copyMissing(path.join(source, name), path.join(target, name), `${relative}/${name}`);
  } else if (!fs.existsSync(target)) fs.copyFileSync(source, target);
  else if (previousHashes[relative]) {
    const hash = require('node:crypto').createHash('sha256').update(fs.readFileSync(target)).digest('hex');
    if (hash === previousHashes[relative]) fs.copyFileSync(source, target);
  }
}
function prepareWorkspace(folder) {
  fs.mkdirSync(folder, {recursive: true});
  for (const name of ['tools', 'build.py', 'fonts.json', 'DICH.md', 'CLAUDE.md', 'Font']) {
    copyMissing(path.join(enginePath(), name), path.join(folder, name), name);
  }
  copyMissing(path.resolve(__dirname, '..', 'requirements.txt'), path.join(folder, 'requirements.txt'), 'requirements.txt');
}
function pythonCheck() {
  const result = spawnSync(settings.python, ['-c',
    'import sys, PIL, fontTools, openpyxl, numpy; print(sys.version.split()[0])'],
    {encoding: 'utf8', timeout: 10000, windowsHide: true});
  return {ok: result.status === 0, version: result.status === 0 ? result.stdout.trim() : '',
    message: result.status === 0 ? '' : (result.stderr || result.error?.message || 'Python could not start').trim()};
}
function emit(event, payload) { if (window && !window.isDestroyed()) window.webContents.send(event, payload); }
function performUpdateCheck() {
  if (updateRequest) return updateRequest;
  updateRequest = checkForUpdate(SOURCE_COMMIT).then(result => {
    lastUpdate = {...result, dismissed: settings.dismissedUpdateCommit === result.latestCommit};
    if (result.status === 'available' && settings.lastNotifiedUpdateCommit !== result.latestCommit) {
      settings.lastNotifiedUpdateCommit = result.latestCommit;
      saveSettings();
      if (app.isPackaged && Notification.isSupported()) {
        const notice = new Notification({title: 'VE-ES Desktop: source update',
          body: `New VE-ES code is available: ${result.latestCommit.slice(0, 7)}`});
        notice.on('click', () => {window?.show(); window?.focus();});
        notice.show();
      }
    }
    return lastUpdate;
  }).catch(error => ({status: 'error', message: error.message})).finally(() => {updateRequest = null;});
  return updateRequest;
}
function displayName(arg) { return arg.name.replace(/^--/, '').replace(/-/g, ' '); }
function makeArgs(tool, values) {
  const args = [...tool.prefix];
  const positionals = tool.args.filter(arg => arg.positional);
  for (let i = 0; i < positionals.length; i++) {
    const arg = positionals[i];
    const value = String(values[arg.name] ?? '').trim();
    if (!value && arg.required) throw new Error(`${displayName(arg)} is required.`);
    if (value || i < positionals.length - 1) args.push(value);
  }
  for (const arg of tool.args.filter(arg => !arg.positional)) {
    const raw = values[arg.name];
    if (arg.kind === 'bool') { if (raw) args.push(arg.name); continue; }
    const list = arg.repeat ? String(raw ?? '').split(/\r?\n/).map(x => x.trim()).filter(Boolean) : [String(raw ?? '').trim()];
    if (!list.length || !list[0]) {
      if (arg.required) throw new Error(`${displayName(arg)} is required.`);
      continue;
    }
    for (const value of list) {
      if (arg.kind === 'number' && !Number.isFinite(Number(value))) throw new Error(`${displayName(arg)} must be a number.`);
      args.push(arg.name, value);
    }
  }
  return args;
}
function createWindow() {
  window = new BrowserWindow({
    width: 1450, height: 940, minWidth: 1050, minHeight: 690,
    title: 'VE-ES Desktop', backgroundColor: '#11131b',
    icon: path.resolve(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {preload: path.join(__dirname, 'preload.js'), contextIsolation: true,
      nodeIntegration: false, sandbox: true}
  });
  window.loadFile(path.join(__dirname, 'index.html'));
  window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
}

app.whenReady().then(() => {
  if (process.platform === 'win32') app.setAppUserModelId('dev.vees.desktop');
  loadSettings();
  prepareWorkspace(settings.workspace);
  saveSettings();
  createWindow();
  const updateTimer = setInterval(() => {
    performUpdateCheck().then(result => emit('update-status', result));
  }, 24 * 60 * 60 * 1000);
  updateTimer.unref();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (currentRun) currentRun.child.kill(); });

ipcMain.handle('state', () => ({tools, settings, python: pythonCheck(), running: !!currentRun,
  sourceCommit: SOURCE_COMMIT, appVersion: app.getVersion()}));
ipcMain.handle('check-update', () => performUpdateCheck());
ipcMain.handle('dismiss-update', (_event, commit) => {
  if (lastUpdate?.status !== 'available' || commit !== lastUpdate.latestCommit) return false;
  settings.dismissedUpdateCommit = commit;
  saveSettings();
  lastUpdate.dismissed = true;
  return true;
});
ipcMain.handle('open-update', () => {
  if (lastUpdate?.status !== 'available') return false;
  return shell.openExternal(lastUpdate.url);
});
ipcMain.handle('choose-workspace', async () => {
  const result = await dialog.showOpenDialog(window, {title: 'Choose a VE-ES project folder',
    defaultPath: settings.workspace, properties: ['openDirectory', 'createDirectory']});
  if (result.canceled) return null;
  prepareWorkspace(result.filePaths[0]);
  settings.workspace = result.filePaths[0];
  saveSettings();
  return {workspace: settings.workspace, python: pythonCheck()};
});
ipcMain.handle('choose-path', async (_event, kind, current) => {
  const defaultPath = current || settings.workspace;
  if (kind === 'save') {
    const result = await dialog.showSaveDialog(window, {defaultPath});
    return result.canceled ? null : result.filePath;
  }
  const properties = kind === 'dir' ? ['openDirectory', 'createDirectory'] : ['openFile', 'openDirectory'];
  const result = await dialog.showOpenDialog(window, {defaultPath, properties});
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle('choose-python', async () => {
  const result = await dialog.showOpenDialog(window, {title: 'Choose a Python executable', properties: ['openFile']});
  if (result.canceled) return null;
  settings.python = result.filePaths[0];
  saveSettings();
  return {python: settings.python, check: pythonCheck()};
});
ipcMain.handle('setup-python', () => {
  if (currentRun) throw new Error('Another command is already running.');
  const runId = `${Date.now()}-setup`;
  const environment = path.join(app.getPath('userData'), 'python-env');
  const executable = process.platform === 'win32' ? path.join(environment, 'Scripts', 'python.exe') : path.join(environment, 'bin', 'python');
  currentRun = {runId, child: null, id: 'setup', cancelled: false};
  emit('run-start', {runId, id: 'setup', title: 'Set up Python', started: new Date().toISOString(),
    command: [settings.python, '-m', 'venv', environment]});
  const step = (command, args) => new Promise(resolve => {
    if (currentRun?.cancelled) return resolve(130);
    emit('run-output', {runId, stream: 'stdout', text: `$ ${[command, ...args].join(' ')}\n`});
    const child = spawn(command, args, {cwd: settings.workspace, windowsHide: true, shell: false});
    currentRun.child = child;
    child.stdout.on('data', data => emit('run-output', {runId, stream: 'stdout', text: data.toString('utf8')}));
    child.stderr.on('data', data => emit('run-output', {runId, stream: 'stderr', text: data.toString('utf8')}));
    child.on('error', error => {emit('run-output', {runId, stream: 'stderr', text: `${error.message}\n`});resolve(1);});
    child.on('close', code => resolve(code ?? 1));
  });
  (async () => {
    let code = fs.existsSync(executable) ? 0 : await step(settings.python, ['-m', 'venv', environment]);
    if (code === 0 && !currentRun.cancelled) code = await step(executable,
      ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', path.join(settings.workspace, 'requirements.txt')]);
    if (code === 0 && !currentRun.cancelled) {
      settings.python = executable;
      saveSettings();
      emit('run-output', {runId, stream: 'stdout', text: '\nPython environment is ready.\n'});
    }
    const cancelled = currentRun.cancelled;
    currentRun = null;
    emit('run-end', {runId, code: cancelled ? 130 : code, signal: cancelled ? 'cancelled' : null});
  })().catch(error => {
    emit('run-output', {runId, stream: 'stderr', text: `${error.stack || error}\n`});
    currentRun = null;
    emit('run-end', {runId, code: 1, signal: null});
  });
  return {runId};
});
ipcMain.handle('open-workspace', () => shell.openPath(settings.workspace));
ipcMain.handle('open-document', (_event, name) => {
  if (!['DICH.md', 'CLAUDE.md', 'Font/README.md', 'tools/README.md'].includes(name)) throw new Error('Unknown document');
  return shell.openPath(path.join(settings.workspace, name));
});
ipcMain.handle('run-tool', (_event, id, values) => {
  if (currentRun) throw new Error('Another command is already running.');
  const tool = byId.get(id);
  if (!tool) throw new Error('Unknown tool.');
  if (!values || typeof values !== 'object') throw new Error('Missing input values.');
  const args = makeArgs(tool, values);
  const script = path.resolve(settings.workspace, tool.script);
  if (!script.startsWith(path.resolve(settings.workspace) + path.sep) && script !== path.resolve(settings.workspace, 'build.py')) throw new Error('Invalid script path.');
  if (!fs.existsSync(script)) throw new Error('Script is missing from the project folder.');
  settings.values[id] = values;
  saveSettings();
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const started = new Date().toISOString();
  const child = spawn(settings.python, ['-u', script, ...args],
    {cwd: settings.workspace, env: {...process.env, PYTHONIOENCODING: 'utf-8'}, windowsHide: true, shell: false});
  currentRun = {runId, child, id};
  emit('run-start', {runId, id, title: tool.title, started, command: [settings.python, tool.script, ...args]});
  child.stdout.on('data', data => emit('run-output', {runId, stream: 'stdout', text: data.toString('utf8')}));
  child.stderr.on('data', data => emit('run-output', {runId, stream: 'stderr', text: data.toString('utf8')}));
  child.on('error', error => emit('run-output', {runId, stream: 'stderr', text: `${error.message}\n`}));
  child.on('close', (code, signal) => {
    currentRun = null;
    settings.history.unshift({id, title: tool.title, started, code, signal});
    settings.history = settings.history.slice(0, 30);
    saveSettings();
    emit('run-end', {runId, code, signal});
  });
  return {runId};
});
ipcMain.handle('cancel-run', () => {
  if (!currentRun) return false;
  currentRun.cancelled = true;
  currentRun.child?.kill();
  return true;
});

module.exports = {makeArgs};
