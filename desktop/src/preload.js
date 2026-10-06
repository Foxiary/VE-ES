const {contextBridge, ipcRenderer} = require('electron');

contextBridge.exposeInMainWorld('vees', {
  state: () => ipcRenderer.invoke('state'),
  chooseWorkspace: () => ipcRenderer.invoke('choose-workspace'),
  choosePath: (kind, current) => ipcRenderer.invoke('choose-path', kind, current),
  choosePython: () => ipcRenderer.invoke('choose-python'),
  setupPython: () => ipcRenderer.invoke('setup-python'),
  openWorkspace: () => ipcRenderer.invoke('open-workspace'),
  openDocument: name => ipcRenderer.invoke('open-document', name),
  run: (id, values) => ipcRenderer.invoke('run-tool', id, values),
  cancel: () => ipcRenderer.invoke('cancel-run'),
  checkUpdates: () => ipcRenderer.invoke('check-update'),
  dismissUpdate: commit => ipcRenderer.invoke('dismiss-update', commit),
  openUpdate: () => ipcRenderer.invoke('open-update'),
  on: (event, callback) => {
    if (!['run-start', 'run-output', 'run-end', 'update-status'].includes(event)) throw new Error('Invalid event');
    const handler = (_event, payload) => callback(payload);
    ipcRenderer.on(event, handler);
    return () => ipcRenderer.removeListener(event, handler);
  }
});
