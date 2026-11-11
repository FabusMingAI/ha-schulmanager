// Exercise notification URLs through the real card lifecycle and detail dialogs.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
  try {
    for (const width of [1280,390]) {
      const page = await browser.newPage({viewport:{width,height:900}});
      const errors=[];
      page.on('pageerror', e=>errors.push(e.message));
      await page.route('https://ha.example.test/**', route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
      await page.goto('https://ha.example.test/dashboard-schule/anna?keep=yes&sm_child=anna&sm_item=letter%2F%26%3F%20%C3%A4#anchor');
      await page.addScriptTag({path:path.resolve(__dirname,'../../custom_components/eltern_portal_schulmanager/www/eltern-portal-schulmanager-card.js')});
      await page.evaluate(()=>{
        window.wsCalls=[];window.serviceCalls=[];
        let release;
        const loaded=new Promise(r=>release=r);
        window.releaseData=release;
        const hass={connection:{},callService:async (...args)=>serviceCalls.push(args),callWS:async msg=>{
          wsCalls.push(msg);
          if(msg.type.endsWith('/data')) {await loaded;return {children:[{key:'anna'},{key:'ben'}]};}
          if(msg.item_id==='missing')throw new Error('Unknown item');
          if(msg.type.endsWith('/item'))return {title:'Elternbrief Klassenausflug',read:false,kind_label:'Elternbrief',tasks:[],body:'Bitte Wanderschuhe mitbringen.',files:[]};
          if(msg.type.endsWith('/task'))return {id:msg.task_id,title:'Buch mitbringen',status:'offen',comment:'',details:'Morgen',type:'mitbringen'};
        }};
        window.testHass=hass;
        window.cards=[];
        for(const [tag,child] of [['card','ben'],['header','anna'],['card','anna'],['card','anna']]){
          const card=document.createElement('eltern-portal-schulmanager-'+tag);
          card.setConfig({child});
          // Keep the list fixture minimal; use real loading, URL handling and dialogs.
          card._render=()=>card._setContent('<ha-card></ha-card>');
          card._subscribe=()=>{};
          document.body.append(card);
          card.hass=hass;
          cards.push(card);
        }
      });
      assert.equal(await page.getByRole('dialog').count(),0);
      await page.evaluate(()=>releaseData());
      const owner=page.locator('eltern-portal-schulmanager-card').nth(1);
      await owner.getByRole('dialog').waitFor();
      assert.match(await owner.getByRole('dialog').innerText(),/Elternbrief Klassenausflug/);
      assert.equal(await page.getByRole('dialog').count(),1);
      assert.deepEqual(await page.evaluate(()=>wsCalls.filter(x=>x.type.endsWith('/item')).map(x=>x.item_id)),['letter/&? ä']);
      assert.equal(await page.evaluate(()=>serviceCalls.filter(x=>x[1]==='mark_read').length),1);
      assert.equal(page.url(),'https://ha.example.test/dashboard-schule/anna?keep=yes#anchor');
      await owner.getByRole('button',{name:'Schließen',exact:true}).last().click();
      await page.evaluate(async ()=>{for(const card of cards)await card._load();});
      assert.equal(await page.getByRole('dialog').count(),0); // No reopening on refresh.
      // Warm app navigation to a task, with existing cards and subscriptions.
      await page.evaluate(()=>{
        history.pushState(null,'','?keep=yes&sm_child=anna&sm_task=task-2#anchor');
        window.dispatchEvent(new Event('location-changed'));
      });
      await owner.getByRole('dialog').waitFor();
      assert.match(await owner.getByRole('dialog').innerText(),/Buch mitbringen/);
      assert.equal(await page.getByRole('dialog').count(),1);
      await owner.getByRole('button',{name:'Schließen',exact:true}).last().click();
      // A removed item gives a clear message, without marking anything read.
      await page.evaluate(()=>{
        history.pushState(null,'','?sm_child=anna&sm_item=missing');
        window.dispatchEvent(new PopStateEvent('popstate'));
      });
      await owner.getByRole('dialog').waitFor();
      assert.match(await owner.getByRole('dialog').innerText(),/Eintrag nicht verfügbar/);
      assert.equal(await page.evaluate(()=>serviceCalls.filter(x=>x[1]==='mark_read').length),1);
      await page.evaluate(()=>{
        for(const card of cards)card.remove();
        history.pushState(null,'','/dashboard-schule/0?sm_child=ben&sm_task=single-task');
        window.dispatchEvent(new Event('location-changed'));
        const card=document.createElement('eltern-portal-schulmanager-card');
        card.setConfig({}); // One combined card for all children.
        card._render=()=>card._setContent('<ha-card></ha-card>');
        card._subscribe=()=>{};
        document.body.append(card);
        card.hass=testHass;
      });
      await page.getByRole('dialog').waitFor();
      assert.equal(await page.getByRole('dialog').count(),1);
      assert.match(await page.getByRole('dialog').innerText(),/Buch mitbringen/);
      assert.equal(page.url(),'https://ha.example.test/dashboard-schule/0');
      assert.equal(await page.evaluate(()=>wsCalls.filter(x=>x.task_id==='single-task').length),1);
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`PASS notification links ${width}px: cold load, delayed data, child selection, one dialog, warm task, missing item, no reopen`);
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
