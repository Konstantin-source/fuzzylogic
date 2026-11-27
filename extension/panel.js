const $ = id => document.getElementById(id);
let windowKey, sequence = 0, lastSelection;
const onboarding = 'Katalog öffnen und anmelden. Dann per Rechtsklick auf das Erweiterungssymbol „Diesen Tab als Artikelkatalog verbinden“ wählen.';

// Runs in the isolated world of the explicitly connected catalogue tab.
async function fetchCatalog(origin, query, useAI) {
  if (location.origin !== origin || !document.querySelector('meta[name="artikelsuche"][content="1"]'))
    return {error:'Bitte den Katalog-Tab erneut verbinden.'};
  const params = new URLSearchParams({q:query});
  const path = useAI ? '/api/ai-search' : '/api/search';
  const response = await fetch(path + '?' + params, {credentials:'same-origin', mode:'same-origin', redirect:'error'});
  if (!response.ok) return {error:'Katalog nicht erreichbar. Bitte die Anmeldung im Katalog-Tab prüfen.'};
  return response.json();
}

function card(item) {
  const article = document.createElement('article');
  const name = document.createElement('strong');
  name.textContent = item.name || 'Ohne Bezeichnung';
  const extra = document.createElement('p');
  extra.textContent = item.extra;
  const copy = document.createElement('button');
  copy.textContent = item.number + '  ⧉';
  copy.title = 'Artikelnummer kopieren';
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(item.number); $('status').textContent = 'Artikelnummer kopiert.'; }
    catch { $('status').textContent = 'Kopieren fehlgeschlagen. Artikelnummer: ' + item.number; }
  };
  article.append(name, extra, copy);
  return article;
}

async function search(useAI = false) {
  const request = ++sequence;
  const query = $('q').value.trim();
  $('results').replaceChildren();
  $('status').textContent = '';
  if (!query) return;
  const {catalog} = await chrome.storage.session.get('catalog');
  if (!catalog || request !== sequence) return;
  $('status').textContent = useAI ? 'KI-Suche läuft …' : 'Katalog wird durchsucht …';
  try {
    const [frame] = await chrome.scripting.executeScript({
      target:{tabId:catalog.tabId}, func:fetchCatalog, args:[catalog.origin, query, useAI]
    });
    if (request !== sequence) return;
    const data = frame?.result;
    if (!data || data.error) throw Error(data?.error || onboarding);
    const groups = new Map();
    for (const item of data.results) {
      const key = JSON.stringify(item.variant_key?.length ? item.variant_key : [item.number]);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    for (const [first, ...variants] of groups.values()) {
      const entry = card(first);
      if (variants.length) {
        const details = document.createElement('details'), summary = document.createElement('summary');
        summary.textContent = 'Weitere Varianten (' + variants.length + ')';
        details.append(summary, ...variants.map(card));
        entry.append(details);
      }
      $('results').append(entry);
    }
    $('status').textContent = data.message || (data.results.length ? '' : 'Keine Treffer.');
  } catch (error) {
    if (request === sequence) $('status').textContent = (error.message || 'Verbindung prüfen.') + ' ' + onboarding;
  }
}

async function refresh() {
  const state = await chrome.storage.session.get(['catalog','connectionError',windowKey]);
  $('connection').textContent = state.catalog ? 'Verbunden mit ' + state.catalog.origin : (state.connectionError || onboarding);
  const selection = state[windowKey];
  if (selection && selection.id !== lastSelection) {
    $('q').value = selection.text;
    if (state.catalog) {
      lastSelection = selection.id;
      await search();
    }
  }
}
$('form').onsubmit = event => { event.preventDefault(); search(); };
$('ai').onclick = () => search(true);
$('q').oninput = () => { sequence++; $('results').replaceChildren(); $('status').textContent = ''; };
chrome.windows.getCurrent().then(win => {
  windowKey = 'selection-' + win.id;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'session' && changes.catalog) {
      sequence++;
      $('results').replaceChildren();
      $('status').textContent = '';
    }
    if (area === 'session' && (changes.catalog || changes.connectionError || changes[windowKey])) refresh();
  });
  refresh();
});
