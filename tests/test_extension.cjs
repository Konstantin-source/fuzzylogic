const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = name => fs.readFileSync('extension/' + name, 'utf8');
const event = () => ({addListener(handler) { this.handle = handler; }});
const tick = () => new Promise(resolve => setImmediate(resolve));

test('selection action transfers only bounded text to the originating window', async () => {
  const writes = [], panels = [];
  const chrome = {
    runtime:{onInstalled:event()}, contextMenus:{onClicked:event()}, action:{onClicked:event()},
    sidePanel:{open:x => panels.push(x)}, tabs:{onRemoved:event()},
    storage:{session:{set:x => writes.push(x)}}
  };
  vm.runInNewContext(source('worker.js'), {chrome, crypto:{randomUUID:() => 'id'}});
  chrome.contextMenus.onClicked.handle({menuItemId:'search', selectionText:'x'.repeat(500), pageUrl:'private'}, {windowId:7});
  assert.equal(panels[0].windowId, 7);
  assert.equal(writes[0]['selection-7'].text.length, 300);
  assert.deepEqual(Object.keys(writes[0]['selection-7']).sort(), ['id','text']);
  const manifest = JSON.parse(source('manifest.json'));
  assert.equal(manifest.host_permissions, undefined);
  assert.ok(!manifest.permissions.includes('tabs'));
});

test('panel searches locally on selection, invokes AI only on request and uses the connected origin', async () => {
  const elements = new Map(), requests = [];
  const element = () => ({children:[],replaceChildren(){this.children=[];},append(...items){this.children.push(...items);}});
  const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const catalog = {origin:'https://katalog.test',tabId:17};
  const state = {catalog,'selection-1':{text:'Rahmen',id:'a'}};
  const chrome = {
    windows:{getCurrent:async () => ({id:1})},
    storage:{session:{get:async () => state},onChanged:event()},
    scripting:{executeScript:async ({target,func,args}) => {
      assert.equal(target.tabId, 17);
      return [{result:await func(...args)}];
    }}
  };
  const location = {origin:catalog.origin};
  const document = {getElementById:get,createElement:element,querySelector:() => true};
  vm.runInNewContext(source('panel.js'), {chrome,location,document,URLSearchParams,fetch:async (url, options) => {
    requests.push(url);
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.redirect, 'error');
    return {ok:true,json:async () => ({results:[{name:'Rahmen',number:'TEST'}]})};
  }});
  await tick();
  assert.deepEqual(requests,['/api/search?q=Rahmen']);
  assert.equal(get('results').children.length, 1);
  get('q').oninput();
  assert.equal(requests.length, 1);
  await get('ai').onclick();
  assert.equal(requests.at(-1),'/api/ai-search?q=Rahmen');
  location.origin = 'https://fremd.test';
  await get('ai').onclick();
  assert.equal(requests.length, 2);
  assert.equal(get('results').children.length, 0);
});
