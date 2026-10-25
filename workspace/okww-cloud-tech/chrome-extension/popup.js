const status = document.querySelector('#status');
document.querySelector('#connect').onclick = async () => {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const result = await chrome.runtime.sendMessage({op: 'connect', tabId: tab.id});
  status.textContent = result.error || '已连接。每日需在本机程序中单独启动。';
};
document.querySelector('#stop').onclick = async () => {
  const result = await chrome.runtime.sendMessage({op: 'stop'});
  status.textContent = result.error || '已停止，游戏页面保留。';
};
