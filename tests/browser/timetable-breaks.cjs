const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true});
 try {
  for(const width of [1280,390]) {
   const page=await browser.newPage({viewport:{width,height:1000}});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<!doctype html><html><body style="margin:0;--primary-color:#1675bd;--secondary-text-color:#68717a;--primary-text-color:#222;--divider-color:#dce2e7;--card-background-color:#fff"></body></html>');
   await page.addScriptTag({path:path.resolve(__dirname,'../../custom_components/eltern_portal_schulmanager/www/eltern-portal-schulmanager-card.js')});
   await page.evaluate(()=>{
    const times=[['08:00','08:45'],['08:50','09:35'],['09:50','10:35'],['10:40','11:25'],['11:40','12:25'],['12:30','13:15'],['14:00','14:45']];
    const child={key:'anna',name:'Anna',timetable:[1,2,3,4,5].flatMap(weekday=>times.map(([start,end],i)=>({weekday,lesson:String(i+1),subject:'M',start,end}))),events:[],substitutions:{available:true,days:[]},schedule_options:{messages:true,holidays:true},schedule:[]};
    const card=document.createElement('eltern-portal-schulmanager-stundenplan');card.setConfig({child:'anna',view:'week'});card._data={today:'2026-11-23',children:[child]};card._hass={};card._subscribe=()=>{};card._load=async()=>{};document.body.append(card);card._render();window.card=card;
   });
   const card=page.locator('eltern-portal-schulmanager-stundenplan');
   assert.equal(await card.locator('.pause-row').count(),6);
   assert.deepEqual(await card.locator('.pause-label').allTextContents(),[5,15,5,15,5,45].map(n=>`ⅡPause · ${n} Min.`));
   assert.equal(await card.locator('.pause-row [colspan="5"]').count(),6);
   assert.match(await card.locator('.pause-long').innerText(),/13:15–14:00.*Pause · 45 Min\./s);
   await card.locator('[data-lesson="3"]').first().click();
   assert.equal(await card.locator('.day-pause').count(),6);
   assert.match(await card.locator('.day-pause').nth(1).innerText(),/09:35–09:50.*Pause · 15 Min\./s);
   // Invalid/missing, overlapping or adjoining times never invent a break.
   const gaps=await card.evaluate(el=>[null,'','bad','25:00','09:00','09:01','08:55'].map(end=>el._lessonBreak({end},{start:'09:00'})));
   assert.deepEqual(gaps.slice(0,6),Array(6).fill(null));
   assert.equal(gaps[6].duration,5);
   await card.getByRole('button',{name:'Zur Wochenansicht',exact:true}).click();
   await card.evaluate(el=>{
    el._data.children[0].schedule=[
     {uid:'break-meeting',title:'Treffen in der Pause',kind:'message',date:'2026-11-23',time:'09:40',time_end:'09:45',status:'confirmed'},
     {uid:'evening',title:'Elternabend',kind:'message',date:'2026-11-23',time:'18:30',time_end:'20:00',status:'confirmed'},
     {uid:'holiday',title:'Schulfrei',kind:'holiday',date:'2026-11-24',end:'2026-11-24',status:'confirmed'}
    ];el._render();
   });
   assert.equal(await card.locator('.pause-row').count(),6);
   assert.equal(await card.locator('.pause-row [data-uid="break-meeting"]').count(),1);
   assert.equal(await card.locator('[data-uid="evening"]').count(),1);
   // A holiday does not get a label in a row shared by the other school days.
   assert.equal(await card.locator('.pause-row td:nth-of-type(2) .pause-label').count(),0);
   await card.locator('[data-uid="break-meeting"]').click();
   assert.equal(await card.locator('.day-pause').count(),6);
   assert.equal(await card.locator('.schedule-entry').filter({hasText:'Treffen in der Pause'}).count(),1);
   await card.locator('[data-day="2026-11-24"]').first().click();
   assert.equal(await card.locator('.day-pause').count(),0);
   await card.getByRole('button',{name:'Zur Wochenansicht',exact:true}).click();
   await card.evaluate(el=>{el._data.children[0].timetable.forEach(l=>{if(l.lesson==='1')l.hidden=true;});el._render();});
   assert.equal(await card.locator('.pause-row').count(),5);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.equal(await card.locator('.wk').evaluate(el=>el.scrollWidth>el.clientWidth),false);
   await page.evaluate(()=>{document.body.style.setProperty('--card-background-color','#202124');document.body.style.setProperty('--secondary-text-color','#ddd');});
   assert.notEqual(await card.locator('.pause-row td').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(241, 247, 245)');
   assert.deepEqual(errors,[]);
   await page.close();console.log(`PASS timetable breaks ${width}px: durations, appointments, holidays, missing times, theme, layout`);
  }
 } finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
