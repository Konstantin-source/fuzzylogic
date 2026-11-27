const $ = id => document.getElementById(id);
const query = $('query'), results = $('results'), dialog = $('dialog');
let currentFile, columns = [], timer, activeSearch = 0, topNumber = '', submittedSearch = '';
let aiItems = [], aiShowingAll = false;
const labels = {number:'Artikelnummer *',name:'Bezeichnung *',extra:'Zusatztext',category:'Warengruppe',unit:'Einheit',ean:'EAN',location:'Lagerort',matchcode:'Matchcode',width:'Breite',height:'Höhe',length:'Länge'};
function el(tag, text, cls) { const e = document.createElement(tag); if(text !== undefined) e.textContent = text; if(cls) e.className = cls; return e; }
async function config() { const c = await (await fetch('/api/config')).json(); $('count').textContent = `${c.count} Artikel im Katalog`; $('rerank').checked = c.rerank_default; $('category').replaceChildren(new Option('Alle Warengruppen',''), ...c.categories.map(x => new Option(x,x))); }
function renderHistory() { const box = $('history'); box.replaceChildren(); let h=[]; try{h=JSON.parse(localStorage.getItem('searchHistory')||'[]')}catch{}; h.forEach(s => { const b=el('button',s); b.onclick=()=>{query.value=s;runSearch()}; box.append(b) }); }
function saveHistory(s) { try { let h=JSON.parse(localStorage.getItem('searchHistory')||'[]'); localStorage.setItem('searchHistory',JSON.stringify([s,...h.filter(x=>x!==s)].slice(0,5))); renderHistory(); } catch {} }
async function copy(number, button) { let ok=false; try { if(navigator.clipboard && window.isSecureContext){await navigator.clipboard.writeText(number);ok=true} } catch {} if(!ok){const t=el('textarea');t.value=number;t.style.position='fixed';t.style.opacity='0';document.body.append(t);t.select();try{ok=document.execCommand('copy')}catch{}t.remove()} button.textContent=ok?'Kopiert ✓':'Kopieren fehlgeschlagen';button.classList.toggle('copied',ok);setTimeout(()=>{button.textContent=number+'  ⧉';button.classList.remove('copied')},1800); }
function groupVariants(items) {
  const groups = new Map();
  for (const item of items) {
    const key = JSON.stringify(item.variant_key?.length ? item.variant_key : [item.number]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.values()];
}
function remember(item, scope) {
  const family = scope === 'family';
  const button = el('button', family ? 'Für Familie merken' : 'Für Artikel merken', 'link');
  button.onclick = async () => {
    const target = family ? 'die Familie „' + item.family + '“' : 'Artikel ' + item.number;
    const term = prompt('Welchen Begriff möchtest du für ' + target + ' merken?', query.value.trim());
    if (!term?.trim()) return;
    try {
      const response = await fetch('/api/articles/' + encodeURIComponent(item.number) + '/synonyms', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({term:term.trim(), scope})
      });
      if (!response.ok) throw Error();
      const data = await response.json();
      if (data.job) poll(data.job);
      await runSearch();
    } catch { alert('Begriff konnte nicht gespeichert werden.'); }
  };
  return button;
}
function articleCard(item) {
  const card = el('article', undefined, 'card');
  const top = el('div', undefined, 'cardtop');
  const button = el('button', item.number + '  ⧉', 'copy');
  button.onclick = () => copy(item.number, button);
  top.append(button, el('span', item.confidence, 'badge ' + item.confidence));
  card.append(top, el('h3', item.name || 'Ohne Bezeichnung'));
  if (item.extra) card.append(el('p', item.extra));
  const axes = [['Breite',item.width], ['Höhe',item.height], ['Länge',item.length]];
  const measures = axes.filter(([,v]) => v).map(([k,v]) => k + ': ' + v);
  if (measures.length) card.append(el('p', measures.join(' · ')));
  if (item.reason) card.append(el('p', item.reason));
  if (item.confidence === 'unsicher') card.append(el('p', 'Maße und Bezeichnung prüfen', 'uncertain'));
  const foot = el('div', undefined, 'cardfooter');
  foot.append(el('span', item.category || ''), remember(item, 'article'));
  if (item.family) foot.append(remember(item, 'family'));
  card.append(foot);
  return card;
}
function render(items, target=results, limit=Infinity) {
  target.replaceChildren();
  if (target === results) topNumber = items[0]?.number || '';
  if (!items.length) {
    target.append(el('div','Keine passenden Artikel gefunden.','empty'));
    return;
  }
  for (const [first, ...others] of groupVariants(items).slice(0, limit)) {
    const card = articleCard(first);
    if (others.length) {
      const details = el('details', undefined, 'variants');
      details.append(el('summary', others.length === 1 ? 'Eine weitere Variante' : others.length + ' weitere Varianten'));
      for (const item of others) details.append(articleCard(item));
      card.append(details);
    }
    target.append(card);
  }
}
function renderAIResults(){
  render(aiItems, $('ai-results'), aiShowingAll ? Infinity : 4);
  const count = groupVariants(aiItems).length;
  const button=$('ai-more');
  button.hidden=count<=4;
  button.textContent=aiShowingAll?'Weniger anzeigen':`Alle ${count} Treffer anzeigen`;
  button.setAttribute('aria-expanded', String(aiShowingAll));
}
$('ai-more').onclick=()=>{aiShowingAll=!aiShowingAll;renderAIResults()};
async function runAISearch(q, category, rerank, sequence){
  const panel=$('ai-panel'), box=$('ai-results'), terms=$('ai-terms');
  panel.hidden=false; box.replaceChildren(); terms.replaceChildren(); $('ai-more').hidden=true;
  $('ai-message').textContent='Die KI sucht nach weiteren passenden Begriffen …';
  $('status').textContent='KI-Suche läuft';
  try{
    const params=new URLSearchParams({q,category,rerank});
    const response=await fetch('/api/ai-search?'+params);
    if(!response.ok)throw Error();
    const data=await response.json();
    if(sequence!==activeSearch)return;
    for(const term of data.terms||[])terms.append(el('span',term));
    $('ai-message').textContent=data.message || (data.terms?.length?'Gesucht mit:':'Keine zusätzlichen Suchbegriffe gefunden.');
    if(data.terms?.length){aiItems=data.results||[];aiShowingAll=false;renderAIResults()}
    $('status').textContent=data.mode==='local'?'Lokaler Modus aktiv':'KI-Suche aktiv';
  }catch{
    if(sequence!==activeSearch)return;
    $('ai-message').textContent='KI-Suche derzeit nicht erreichbar. Direkte Treffer bleiben verfügbar.';
    $('status').textContent='Lokaler Modus aktiv';
  }
}
async function runSearch(useAI=false){
  const q=query.value.trim(), sequence=++activeSearch;
  const category=$('category').value, rerank=$('rerank').checked;
  if(!q){$('ai-panel').hidden=true;results.replaceChildren(el('div','Beschreibung, Artikelnummer oder Maße eingeben.','empty'));topNumber='';return}
  if(useAI){submittedSearch=q;runAISearch(q,category,rerank,sequence)}
  else{$('ai-panel').hidden=true;$('status').textContent='Lokaler Modus aktiv'}
  try{
    const params=new URLSearchParams({q,category,rerank:false,use_ai:false});
    const response=await fetch('/api/search?'+params);
    if(!response.ok)throw Error();
    const data=await response.json();
    if(sequence!==activeSearch)return;
    render(data.results);saveHistory(q);
  }catch{if(sequence===activeSearch)results.replaceChildren(el('div','Suche derzeit nicht erreichbar.','empty'))}
}
query.addEventListener('input',()=>{activeSearch++;topNumber='';submittedSearch='';$('ai-panel').hidden=true;clearTimeout(timer);timer=setTimeout(()=>runSearch(),350)});
$('rerank').onchange=()=>{submittedSearch='';runSearch()};
$('category').onchange=()=>{submittedSearch='';runSearch()};
$('submit-search').onclick=()=>{clearTimeout(timer);submittedSearch='';runSearch(true)};
document.addEventListener('keydown',e=>{if(e.key==='/' && !dialog.open && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();query.focus()}if(e.key==='Escape'&&!dialog.open){query.value='';submittedSearch='';runSearch();query.focus()}if(e.key==='Enter'&&!dialog.open&&document.activeElement===query){e.preventDefault();clearTimeout(timer);if(submittedSearch===query.value.trim()&&topNumber)results.querySelector('.copy')?.click();else runSearch(true)}});
$('open-import').onclick=()=>dialog.showModal();$('file').onchange=e=>preview(e.target.files[0]);const drop=$('drop');drop.ondragover=e=>{e.preventDefault()};drop.ondrop=e=>{e.preventDefault();preview(e.dataTransfer.files[0])};
async function preview(file){if(!file)return;currentFile=file;$('error').textContent='';$('import').disabled=true;const form=new FormData();form.append('file',file);try{const r=await fetch('/api/preview',{method:'POST',body:form});const data=await r.json();if(!r.ok)throw Error(data.detail);columns=data.columns;$('file-info').textContent=`${file.name} · ${data.count} Zeilen`;$('mapping').replaceChildren();for(const [field,label] of Object.entries(labels)){const l=el('label',label),s=el('select');s.id='map-'+field;s.append(new Option('Nicht zugeordnet',''),...columns.map(c=>new Option(c,c)));s.value=data.mapping[field]||'';l.append(s);$('mapping').append(l)}$('import').disabled=false}catch(e){$('error').textContent=e.message||'Datei konnte nicht gelesen werden.'}}
$('import').onclick=async()=>{const mapping={};for(const field of Object.keys(labels))mapping[field]=$('map-'+field).value;const form=new FormData();form.append('file',currentFile);form.append('mapping',JSON.stringify(mapping));$('import').disabled=true;$('error').textContent='';try{const r=await fetch('/api/import',{method:'POST',body:form});const data=await r.json();if(!r.ok)throw Error(data.detail);$('file-info').textContent=`${data.count} Artikel importiert${data.without_name ? ` · ${data.without_name} ohne Bezeichnung` : ''}`;await config();poll(data.job);runSearch()}catch(e){$('error').textContent=e.message||'Import fehlgeschlagen.';$('import').disabled=false}};
async function poll(job){$('progress-wrap').hidden=false;try{const r=await fetch('/api/jobs/'+job);const j=await r.json();$('progress').value=j.total?100*j.done/j.total:(j.status==='done'?100:0);$('progress-text').textContent=j.message+(j.total?` ${j.done}/${j.total}`:'');if(j.status==='running')setTimeout(()=>poll(job),700);else $('import').disabled=false}catch{$('progress-text').textContent='Status nicht erreichbar.'}}
$('compact').onclick = () => window.open('/?kompakt=1', 'artikelkatalog', 'popup,width=490,height=760');
const compactView = new URLSearchParams(window.location?.search).has('kompakt');
if (compactView) document.body.classList.add('compact');
if (window.location?.protocol === 'https:') document.querySelector('.extension-download').href = '/browser-erweiterung.zip?https=true';
if (compactView && window.location.hash) {
  const selected = new URLSearchParams(window.location.hash.slice(1)).get('q');
  if (selected) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    query.value = selected.trim().slice(0,300);
    runSearch();
  }
}
config();renderHistory();
