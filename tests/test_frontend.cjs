const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function startApp() {
  const elements = new Map();
  const documentHandlers = {};
  const requests = [];
  let nextTimer = 0;
  const timers = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        value: '', checked: false, open: false, tagName: 'DIV',
        handlers: {}, classList: {toggle() {}, remove() {}},
        addEventListener(name, handler) { this.handlers[name] = handler; },
        replaceChildren() {}, append() {}, querySelector() { return null; }, focus() {},
      });
    }
    return elements.get(id);
  }
  const document = {
    activeElement: null, body: {append() {}},
    getElementById: element,
    createElement: () => ({classList:{toggle() {}, remove() {}}, append() {}, remove() {}, select() {}}),
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
  app.element('submit-search').onclick();
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'true');
});

test('pressing Enter explicitly requests AI', () => {
  const app = startApp();
  const query = app.element('query');
  query.value = 'Schraube';
  app.document.activeElement = query;
  app.documentHandlers.keydown({key:'Enter', preventDefault() {}});
  assert.equal(searchRequests(app).at(-1).get('use_ai'), 'true');
});
