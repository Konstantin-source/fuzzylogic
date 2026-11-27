chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({id:'connect', title:'Diesen Tab als Artikelkatalog verbinden', contexts:['action']});
  chrome.contextMenus.create({id:'search', title:'Im Artikelkatalog suchen', contexts:['selection']});
});

chrome.action.onClicked.addListener(tab => chrome.sidePanel.open({windowId:tab.windowId}));

async function connect(tab) {
  const url = new URL(tab.url);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:'))
    throw Error('Öffne den Katalog über HTTPS oder localhost.');
  const [page] = await chrome.scripting.executeScript({
    target:{tabId:tab.id},
    func:() => document.querySelector('meta[name="artikelsuche"]')?.content === '1'
  });
  if (!page.result) throw Error('Bitte zuerst die aktuelle Katalog-Webapp öffnen und anmelden.');
  await chrome.storage.session.set({catalog:{tabId:tab.id, origin:url.origin}, connectionError:''});
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  chrome.sidePanel.open({windowId:tab.windowId});
  if (info.menuItemId === 'search') {
    chrome.storage.session.set({['selection-' + tab.windowId]:{
      text:(info.selectionText || '').trim().slice(0,300), id:crypto.randomUUID()
    }});
  } else if (info.menuItemId === 'connect') {
    connect(tab).catch(error => chrome.storage.session.set({catalog:null, connectionError:error.message}));
  }
});

chrome.tabs.onRemoved.addListener(async tabId => {
  const {catalog} = await chrome.storage.session.get('catalog');
  if (catalog?.tabId === tabId) await chrome.storage.session.remove('catalog');
});
