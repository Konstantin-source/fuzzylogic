chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({id:'connect', title:'Diesen Tab als Artikelkatalog verbinden', contexts:['action']});
  chrome.contextMenus.create({id:'search', title:'Im Artikelkatalog suchen', contexts:['selection']});
  chrome.contextMenus.create({id:'sidebar', title:'Schnellsuche in der Seitenleiste', contexts:['action']});
});

function openCatalog(tab, selection = '') {
  const home = chrome.runtime.getManifest().homepage_url;
  if (!home) {
    // A source checkout has no server address. Keep the existing tab-based search available.
    chrome.sidePanel.open({windowId:tab.windowId});
    if (selection) chrome.storage.session.set({['selection-' + tab.windowId]:{text:selection, id:crypto.randomUUID()}});
    return;
  }
  const url = new URL('/', home);
  url.searchParams.set('kompakt', '1');
  if (selection) url.hash = new URLSearchParams({q:selection}).toString();
  return chrome.windows.create({url:url.href, type:'popup', width:520, height:760, incognito:tab.incognito});
}

chrome.action.onClicked.addListener(tab => openCatalog(tab));

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
  if (info.menuItemId === 'search') {
    return openCatalog(tab, (info.selectionText || '').trim().slice(0,300));
  }
  chrome.sidePanel.open({windowId:tab.windowId});
  if (info.menuItemId === 'connect') {
    connect(tab).catch(error => chrome.storage.session.set({catalog:null, connectionError:error.message}));
  }
});

chrome.tabs.onRemoved.addListener(async tabId => {
  const {catalog} = await chrome.storage.session.get('catalog');
  if (catalog?.tabId === tabId) await chrome.storage.session.remove('catalog');
});
