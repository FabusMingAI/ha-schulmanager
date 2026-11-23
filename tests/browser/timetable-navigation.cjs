const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true});
  try {
    for (const width of [1280,390]) for (const nested of [false,true]) {
      const page = await browser.newPage({viewport:{width,height:700}});
      const errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      await page.setContent(`<html><head><style>body{margin:0;font:15px Arial;--primary-color:#1675bd;--primary-text-color:#222;--secondary-text-color:#68717a;--secondary-background-color:#f1f4f7;--divider-color:#dce2e7;--card-background-color:#fff;--header-height:0px}ha-card{display:block;background:white}</style></head><body></body></html>`);
      await page.addScriptTag({path:path.resolve(__dirname,'../../custom_components/eltern_portal_schulmanager/www/eltern-portal-schulmanager-card.js')});
      await page.evaluate(nested => {
        let parent=document.body;
        if(nested) {
          const host=document.createElement('div');document.body.append(host);
          const root=host.attachShadow({mode:'open'});
          const container=document.createElement('div');container.id='dashboard-scroll';container.style.cssText='height:650px;overflow:auto';root.append(container);parent=container;
        }
        window.scrollContainer=nested?parent:document.scrollingElement;
        const spacer=document.createElement('div');spacer.style.height='400px';parent.append(spacer);
        const lessons=Array.from({length:9},(_,i)=>({weekday:1,lesson:String(i+1),subject:'M',start:`${String(8+i).padStart(2,'0')}:00`,end:i===8?'':`${String(8+i).padStart(2,'0')}:45`,teacher_label:'AB (Anna Beispiel)',room:'101'}));
        const child={key:'anna',name:'Anna',classname:'8b',timetable:lessons,substitutions:{available:true,days:[]},events:[],schedule_options:{messages:true,holidays:true},schedule:[{uid:'course',kind:'message',title:'Robotikkurs',date:'2026-11-30',time:'10:00',time_end:'10:45',status:'confirmed',details:'Bitte Material mitbringen.'}]};
        const card=document.createElement('eltern-portal-schulmanager-stundenplan');
        card.setConfig({child:'anna',view:'week',show_name:true});card._data={today:'2026-11-23',children:[child]};card._hass={};card._subscribe=()=>{};card._load=async()=>{};
        parent.append(card);card._render();window.card=card;
        const bottom=document.createElement('div');bottom.style.height='900px';parent.append(bottom);
      },nested);
      // Locator crosses the simulated HA dashboard's shadow root as well as the card's.
      const card=page.locator('eltern-portal-schulmanager-stundenplan');
      assert.equal(await card.getByRole('button',{name:'Zur Wochenansicht',exact:true}).count(),0);
      assert.match(await card.locator('.wk th').allTextContents().then(x=>x.join(' ')),/08:00–08:45/);
      assert.match(await card.locator('.wk th').allTextContents().then(x=>x.join(' ')),/16:00/);
      assert.doesNotMatch(await card.locator('.wk th').allTextContents().then(x=>x.join(' ')),/16:00–/);
      await card.getByRole('button',{name:'Woche vor',exact:true}).click();
      assert.match(await card.locator('.wkn').innerText(),/30\.11\./);
      for (const selector of ['[data-lesson="3"]','[data-schedule-day]']) {
        const trigger=card.locator(selector).first();
        await trigger.scrollIntoViewIfNeeded();
        await trigger.focus();
        const previous=await page.evaluate(()=>scrollContainer.scrollTop);
        await page.keyboard.press('Enter');
        await card.getByRole('button',{name:'Zur Wochenansicht',exact:true}).waitFor();
        assert.equal(await card.locator('.wk').count(),0);
        if(selector.includes('schedule')) assert.match(await card.locator('ha-card').innerText(),/Bitte Material mitbringen/);
        await page.evaluate(()=>{scrollContainer.scrollTop=card.getBoundingClientRect().top+scrollContainer.scrollTop+350;});
        const button=card.getByRole('button',{name:'Zur Wochenansicht',exact:true});
        const bounds=await button.boundingBox();
        assert.ok(bounds.y>=0 && bounds.y+bounds.height<=650,`sticky button ${JSON.stringify(bounds)}`);
        await button.click();
        await card.locator('.wk').waitFor();
        await page.waitForFunction(previous=>Math.abs(scrollContainer.scrollTop-previous)<=1,previous);
        assert.match(await card.locator('.wkn').innerText(),/30\.11\./);
        assert.equal(await card.locator(selector).first().evaluate(el=>el.getRootNode().activeElement===el),true);
      }
      // Existing week toggle takes the same return path; switching days preserves context.
      await card.locator('[data-lesson="1"]').first().click();
      await card.locator('[data-day]').first().click();
      await card.getByRole('button',{name:'Woche',exact:true}).click();
      assert.match(await card.locator('.wkn').innerText(),/30\.11\./);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      assert.equal(await card.locator('.wk').evaluate(el=>el.scrollWidth>el.clientWidth),false);
      assert.deepEqual(errors,[]);
      if(!nested) {
        await card.scrollIntoViewIfNeeded();
        await page.screenshot({path:`/tmp/schulmanager-navigation-${width}.png`,fullPage:true});
      }
      await page.close();
      console.log(`PASS timetable return ${width}px ${nested?'HA shadow scroll':'document scroll'}`);
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
