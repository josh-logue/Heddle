// The desktop shell's preload: runs in the page's sandbox before the app, and puts the
// bridge (src/platform/bridge.ts) on the page as window.heddleDesktop. Plain CommonJS
// (a sandboxed preload can't be a module or TypeScript). Expose plain data and small
// functions only: never ipcRenderer itself.
"use strict";
const { contextBridge, ipcRenderer, webUtils } = require("electron");

/** Channel names: as CHANNELS in src/platform/bridge.ts (a test checks they match). */
const CH = {
  start: "heddle:start",
  openDialog: "heddle:open-dialog",
  saveDialog: "heddle:save-dialog",
  read: "heddle:read",
  write: "heddle:write",
  saveExport: "heddle:save-export",
  pdf: "heddle:pdf",
  backups: "heddle:backups",
  backup: "heddle:backup",
  log: "heddle:log",
  picture: "heddle:picture",
  report: "heddle:report",
  route: "heddle:route",
  open: "heddle:open",
  takeOpen: "heddle:take-open",
  asksBeforeClosing: "heddle:asks-before-closing",
  closeRequest: "heddle:close-request",
  closeNow: "heddle:close-now",
};

const start = ipcRenderer.sendSync(CH.start);
if (start) {
  contextBridge.exposeInMainWorld("heddleDesktop", {
    info: start.info,
    seed: start.seed,
    open: start.open,
    newBoard: !!start.newBoard,
    first: start.first,
    report: (path, blank) => ipcRenderer.send(CH.report, path == null ? null : String(path), !!blank),
    route: (path, blank) => ipcRenderer.invoke(CH.route, path == null ? null : String(path), !!blank),
    onOpen: (listener) => {
      ipcRenderer.on(CH.open, () => listener());
    },
    takeOpen: () => ipcRenderer.invoke(CH.takeOpen),
    onCloseRequest: (listener) => {
      ipcRenderer.on(CH.closeRequest, () => listener());
      ipcRenderer.send(CH.asksBeforeClosing);
    },
    closeNow: () => ipcRenderer.send(CH.closeNow),
    openDialog: () => ipcRenderer.invoke(CH.openDialog),
    saveDialog: (name, folder) => ipcRenderer.invoke(CH.saveDialog, String(name), folder == null ? null : String(folder)),
    read: (path) => ipcRenderer.invoke(CH.read, String(path)),
    write: (path, text) => ipcRenderer.invoke(CH.write, String(path), String(text)),
    saveExport: (data, fileName, description, extension) =>
      ipcRenderer.invoke(CH.saveExport, data, String(fileName), String(description), String(extension)),
    pdf: (svg, title) => ipcRenderer.invoke(CH.pdf, String(svg), String(title)),
    backups: (board) => ipcRenderer.invoke(CH.backups, String(board)),
    backup: (board, text, now, force) => ipcRenderer.invoke(CH.backup, String(board), String(text), Number(now), !!force),
    log: (text) => ipcRenderer.send(CH.log, String(text)),
    picture: (picture, board) => ipcRenderer.invoke(CH.picture, String(picture), board == null ? null : String(board)),
    pathFor: (file) => {
      try {
        return webUtils.getPathForFile(file);
      } catch {
        return "";
      }
    },
  });
}
