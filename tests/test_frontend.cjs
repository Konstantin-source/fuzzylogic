const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function startApp(aiResponse = {results: [], terms: ['Schattenfugenrahmen'], mode: 'terms', message: ''}) {
  const elements = new Map();
  const documentHandlers = {};
  const requests = [];
  let nextTimer = 0;
  const timers = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        value: '', checked: false, open: false, tagName: 'DIV',
        handlers: {}, children: [], attributes: {}, classList: {toggle() {}, remove() {}},
        addEventListener(name, handler) { this.handlers[name] = handler; },
        setAttribute(name, value) { this.attributes[name] = value; },
        replaceChildren(...children) { this.children = children; }, append(...children) { this.children.push(...children); }, querySelector() { return null; }, focus() {},
      });
    }
    return elements.get(id);
  }
  const document = {
    activeElement: null, body: {append() {}},
    getElementById: element,
    createElement: tag => ({tag, children:[], classList:{toggle() {}, remove() {}}, append(...items) {this.children.push(...items);}, remove() {}, select() {}}),
    addEventListener(name, handler) { documentHandlers[name] = handler; },
  };
  const context = {
    document, URLSearchParams, Option: function Option(text, value) { this.text=text; this.value=value; },
    localStorage: {getItem() {return '[]';}, setItem() {}},
    window: {}, navigator: {}, prompt() {}, alert() {},
    fetch: async url => {
      requests.push(url);
      return {ok: true, json: async () => url === '/api/config'
        ? {count: 0, rerank_default: false, categories: []}
        : String(url).startsWith('/api/ai-search?')
          ? aiResponse
          : {results: [], mode: 'local'}};
    },
    setTimeout(fn) { const id=++nextTimer; timers.set(id,fn); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(fs.readFileSync('app/static/app.js', 'utf8'), context);
  return {element, document, documentHandlers, requests, timers};
}

function searchRequests(app) {
  return app.requests.filter(url => String(url).startsWith('/api/search?')).map(url => new URLSearchParams(String(url).split('?')[1]));
}

test('typing and option changes stay local, button explicitly requests AI', async () => {
  const app = startApp();
  app.element('query').value = 'Winkel';
  app.element('query').handlers.input();
  for (const fn of app.timers.values()) fn();
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'false');
  app.element('category').onchange();
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'false');
  app.element('rerank').onchange();
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'false');
  assert.equal(app.requests.filter(url => String(url).startsWith('/api/ai-search?')).length, 0);
  app.element('submit-search').onclick();
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'false');
  assert.equal(app.requests.filter(url => String(url).startsWith('/api/ai-search?')).length, 1);
});

test('pressing Enter explicitly requests AI', () => {
  const app = startApp();
  const query = app.element('query');
  query.value = 'Schraube';
  app.document.activeElement = query;
  app.documentHandlers.keydown({key:'Enter', preventDefault() {}});
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'false');
  assert.equal(app.requests.filter(url => String(url).startsWith('/api/ai-search?')).length, 1);
});

test('AI panel presents generated search terms separately', async () => {
  const app = startApp();
  app.element('query').value = 'Rahmen für Keilrahmen';
  app.element('submit-search').onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.element('ai-panel').hidden, false);
  assert.equal(app.element('ai-terms').children[0].textContent, 'Schattenfugenrahmen');
  assert.equal(app.element('status').textContent, 'KI-Suche aktiv');
});

test('AI panel can be collapsed and extra results revealed', async () => {
  const html = fs.readFileSync('app/static/index.html', 'utf8');
  assert.match(html, /<details id="ai-panel"/);
  assert.match(html, /<summary class="ai-heading">/);
  const items = Array.from({length: 6}, (_, i) => ({number: `A${i}`, name: 'Rahmen', confidence: 'unsicher'}));
  const app = startApp({results: items, terms: ['Rahmen'], mode:'terms', message:''});
  app.element('query').value = 'Rahmen';
  app.element('submit-search').onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.element('ai-results').children.length, 4);
  assert.equal(app.element('ai-more').hidden, false);
  assert.equal(app.element('ai-more').attributes['aria-expanded'], 'false');
  app.element('ai-more').onclick();
  assert.equal(app.element('ai-results').children.length, 6);
  assert.equal(app.element('ai-more').attributes['aria-expanded'], 'true');
});

test('groups variants before limiting visible cards and keeps the best SKU on top', async () => {
  const items = Array.from({length: 7}, (_, i) => ({
    number:'SKU-' + i, name:'Rahmen', family:'Rahmen', variant_key:[i < 4 ? 'Serie A' : i]
  }));
  const app = startApp({results:items, terms:['Rahmen'], mode:'terms'});
  app.element('query').value = 'Rahmen';
  app.element('submit-search').onclick();
  await new Promise(resolve => setImmediate(resolve));
  const cards = app.element('ai-results').children;
  assert.equal(cards.length, 4);
  assert.equal(app.element('ai-more').hidden, true);
  assert.match(cards[0].children[0].children[0].textContent, /SKU-0/);
  const variants = cards[0].children.at(-1);
  assert.equal(variants.tag, 'details');
  assert.equal(variants.children[0].textContent, '3 weitere Varianten');
  assert.match(variants.children[1].children[0].children[0].textContent, /SKU-1/);
});
