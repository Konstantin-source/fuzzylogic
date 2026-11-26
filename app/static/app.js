const $ = id => document.getElementById(id);
const query = $('query'), results = $('results'), dialog = $('dialog');
let currentFile, columns = [], timer, activeSearch = 0, topNumber = '', submittedSearch = '';
let aiItems = [], aiShowingAll = false;
const labels = {number:'Artikelnummer *',name:'Bezeichnung *',extra:'Zusatztext',category:'Warengruppe',unit:'Einheit',ean:'EAN',location:'Lagerort',matchcode:'Matchcode',width:'Breite',height:'Höhe',length:'Länge'};
function el(tag, text, cls) { const e = document.createElement(tag); if(text !== undefined) e.textContent = text; if(cls) e.className = cls; return e; }
async function config() { const c = await (await fetch('/api/config')).json(); $('count').textContent = `${c.count} Artikel im Katalog`; $('rerank').checked = c.rerank_default; $('category').replaceChildren(new Option('Alle Warengruppen',''), ...c.categories.map(x => new Option(x,x))); }
function history() { const box = $('history'); box.replaceChildren(); let h=[]; try{h=JSON.parse(localStorage.getItem('searchHistory')||'[]')}catch{}; h.forEach(s => { const b=el('button',s); b.onclick=()=>{query.value=s;runSearch()}; box.append(b) }); }
function saveHistory(s) { try { let h=JSON.parse(localStorage.getItem('searchHistory')||'[]'); localStorage.setItem('searchHistory',JSON.stringify([s,...h.filter(x=>x!==s)].slice(0,5))); history(); } catch {} }
async function copy(number, button) { let ok=false; try { if(navigator.clipboard && window.isSecureContext){await navigator.clipboard.writeText(number);ok=true} } catch {} if(!ok){const t=el('textarea');t.value=number;t.style.position='fixed';t.style.opacity='0';document.body.append(t);t.select();try{ok=document.execCommand('copy')}catch{}t.remove()} button.textContent=ok?'Kopiert ✓':'Kopieren fehlgeschlagen';button.classList.toggle('copied',ok);setTimeout(()=>{button.textContent=number+'  ⧉';button.classList.remove('copied')},1800); }
function render(items,target=results){target.replaceChildren(); if(target===results)topNumber=items[0]?.number||''; if(!items.length){target.append(el('div','Keine passenden Artikel gefunden.','empty'));return} for(const item of items){const card=el('article',undefined,'card'), top=el('div',undefined,'cardtop'), button=el('button',item.number+'  ⧉','copy');button.onclick=()=>copy(item.number,button);top.append(button,el('span',item.confidence,'badge '+item.confidence));card.append(top,el('h3',item.name||'Ohne Bezeichnung'));if(item.extra)card.append(el('p',item.extra));const measures=[['Breite',item.width],['Höhe',item.height],['Länge',item.length]].filter(([,v])=>v).map(([k,v])=>k+': '+v);if(measures.length)card.append(el('p',measures.join(' · ')));if(item.reason)card.append(el('p',item.reason));if(item.confidence==='unsicher')card.append(el('p','Unsicher – bitte Maße/Bezeichnung prüfen','uncertain'));const foot=el('div',undefined,'cardfooter'), remember=el('button','＋ Begriff merken','link');remember.onclick=async()=>{const term=prompt('Welchen Begriff möchtest du für diesen Artikel merken?');if(!term?.trim())return;const r=await fetch('/api/articles/'+encodeURIComponent(item.number)+'/synonyms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({term:term.trim()})});if(!r.ok){alert('Begriff konnte nicht gespeichert werden.');return}const data=await r.json();poll(data.job);runSearch()};foot.append(el('span',item.category||'Ohne Warengruppe'),remember);card.append(foot);target.append(card)}}
function renderAIResults(){
  render(aiShowingAll ? aiItems : aiItems.slice(0,4), $('ai-results'));
  const button=$('ai-more');
  button.hidden=aiItems.length<=4;
  button.textContent=aiShowingAll?'Weniger anzeigen':`Alle ${aiItems.length} Treffer anzeigen`;
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
config();history();
