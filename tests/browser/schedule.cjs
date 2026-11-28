const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true});
  try {
    for (const width of [1280,390]) {
      const page = await browser.newPage({viewport:{width,height:1000}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent('<!doctype html><html lang="de"><body></body></html>');
      await page.addScriptTag({path:path.resolve(__dirname,'../../custom_components/eltern_portal_schulmanager/www/eltern-portal-schulmanager-card.js')});
      await page.evaluate(() => {
        const c = {key:'anna',name:'Anna',timetable:[{weekday:1,lesson:'7',subject:'M',start:'14:00',end:'14:45',optional:true,schedule_uid:'lesson-one'}],
          substitutions:{available:true,days:[]},events:[],schedule_options:{messages:true,holidays:true},schedule:[
            {uid:'course',title:'Robotikkurs',kind:'message',date:'2026-12-21',weekday:1,repeat_until:'2027-01-11',time:'14:00',time_end:'15:30',status:'proposed',sources:[{title:'Kursangebot',url:'https://example.org/course'}]},
            {uid:'holiday',title:'Weihnachtsferien',kind:'holiday',date:'2026-12-24',end:'2027-01-08',status:'confirmed',source_url:'https://example.org/holidays'},
            {uid:'past',title:'Archiv-Ausflug',kind:'message',date:'2026-12-14',status:'confirmed'},
          ]};
        window.calls = [];
        const card = document.createElement('eltern-portal-schulmanager-stundenplan');
        card.setConfig({child:'anna'});
        card._data = {today:'2026-12-21',children:[c],schedule_progress:{total:20,pending:3,failed:1,unreadable:2}};
        card._sel = {anna:'2026-12-21'};
        card._hass = {callService:async (domain,service,data) => {
          calls.push({service,data});
          if(service === 'timetable_entry') {
            const e = c.schedule.find(e => e.uid === data.event_id);
            if(e) {if(data.action === 'confirm')e.status='confirmed'; else e.hidden=data.action==='hide';}
            else c.timetable[0].hidden=data.action==='hide';
          }
          if(service === 'timetable_options') c.schedule_options=data;
        }};
        card._subscribe = () => {};
        card._load = async () => {};
        document.body.append(card);
        card._render();
      });
      const card = page.locator('eltern-portal-schulmanager-stundenplan');
      assert.match(await card.locator('ha-card').innerText(),/17 \/ 20 Mitteilungen/);
      assert.match(await card.locator('ha-card').innerText(),/Vorschlag/);
      assert.equal(await card.locator('.schedule-entry.proposed').count(),1);
      assert.equal(await card.locator('.wk [data-uid="course"]').count(),0);
      assert.equal(await card.getByRole('button',{name:'Ja, relevant',exact:true}).count(),1);
      await card.locator('[data-schedule-open]').filter({hasText:'Robotikkurs'}).click();
      assert.equal(await card.getByRole('link',{name:'Kursangebot'}).getAttribute('href'),'https://example.org/course');
      await card.getByRole('button',{name:'Ja, relevant',exact:true}).click();
      await card.locator('[data-schedule-open]').filter({hasText:'Robotikkurs'}).click();
      assert.match(await card.locator('ha-card').innerText(),/Überschneidung mit Unterricht/);
      await card.getByRole('button',{name:'Serie entfernen',exact:true}).click();
      assert.doesNotMatch(await card.locator('ha-card').innerText(),/Robotikkurs/);
      await card.getByRole('button',{name:'Einträge verwalten'}).click();
      await card.locator('[data-schedule-open]').filter({hasText:'Robotikkurs'}).click();
      await card.getByRole('button',{name:'Wiederherstellen',exact:true}).click();
      assert.match(await card.locator('ha-card').innerText(),/Robotikkurs/);
      await card.locator('[data-daylesson]').click();
      await card.getByRole('button',{name:'Optionalen Eintrag entfernen'}).click();
      assert.equal(await card.locator('.les').count(),0);
      await card.getByRole('button',{name:'Wiederherstellen',exact:true}).click();
      await card.getByRole('button',{name:'Woche',exact:true}).click();
      assert.equal(await card.locator('table').getByRole('button',{name:/Robotikkurs.*Tagesansicht öffnen/}).count(),1);
      assert.equal(await card.locator('table').locator('[data-schedule-action]').count(),0);
      await card.evaluate(element => {
        element._data.children[0].schedule[0].title='Robotikkurs für mathematische und naturwissenschaftliche Wettbewerbe mit anschließender Projektvorstellung für alle interessierten Eltern und Schüler';
        element._render();
      });
      const compact = card.getByRole('button',{name:/Robotikkurs für mathematische.*Tagesansicht öffnen/});
      const titleLayout = await compact.locator('.appointment-title').evaluate(el => ({height:el.getBoundingClientRect().height, scrollHeight:el.scrollHeight, clamp:getComputedStyle(el).webkitLineClamp}));
      assert.equal(titleLayout.clamp,'2');
      assert.ok(titleLayout.height <= 36);
      assert.ok(titleLayout.scrollHeight > titleLayout.height);
      assert.ok((await compact.boundingBox()).height <= 42);
      await compact.focus();
      await page.keyboard.press('Enter');
      assert.equal(await card.locator('.wk table').count(),0);
      assert.match(await card.locator('ha-card').innerText(),/Robotikkurs für mathematische und naturwissenschaftliche Wettbewerbe/);
      assert.equal(await card.getByRole('button',{name:'Serie entfernen',exact:true}).count(),1);
      await card.getByRole('button',{name:'Woche',exact:true}).click();
      await card.getByRole('button',{name:'Woche vor',exact:true}).click();
      assert.ok(await card.getByRole('button',{name:/Weihnachtsferien.*Tagesansicht öffnen/}).count() > 0);
      assert.doesNotMatch(await card.locator('ha-card').innerText(),/Robotikkurs/);
      assert.equal(await card.locator('[data-lesson]').count(),0);
      await card.getByRole('button',{name:'Ferien an',exact:true}).click();
      assert.equal(await card.locator('[data-lesson]').count(),1);
      await card.getByRole('button',{name:'Woche zurück',exact:true}).click();
      await card.getByRole('button',{name:'Woche zurück',exact:true}).click();
      assert.equal(await card.getByRole('button',{name:/Archiv-Ausflug.*Tagesansicht öffnen/}).count(),1);
      await card.getByRole('button',{name:'Archiv erneut prüfen'}).click();
      assert.equal(await page.evaluate(()=>calls.at(-1).service),'rescan_schedule');
      await card.evaluate(el=>{
        el._data.children[0].schedule=[
          {uid:'bayeux',title:'Frankreich-Austausch Bayeux',kind:'message',date:'2026-12-21',end:'2026-12-23',status:'proposed'},
          {uid:'clermont',title:'Frankreich-Austausch Clermont-Ferrand',kind:'message',date:'2026-12-21',end:'2026-12-24',status:'proposed'}
        ];el._wkOff={anna:0};el._render();
      });
      assert.equal(await card.locator('.wk .week-appointment').count(),0);
      assert.equal(await card.locator('.schedule-entry.proposed').count(),2);
      assert.match(await card.locator('.schedule-entry').first().innerText(),/21.12.2026–23.12.2026/);
      const bayeux=card.locator('.schedule-entry').filter({hasText:'Frankreich-Austausch Bayeux'});
      await bayeux.getByRole('button',{name:'Nein, nicht relevant',exact:true}).click();
      assert.equal(await card.locator('.wk .week-appointment').count(),0);
      const clermont=card.locator('.schedule-entry').filter({hasText:'Frankreich-Austausch Clermont-Ferrand'});
      await clermont.getByRole('button',{name:'Ja, relevant',exact:true}).click();
      assert.equal(await card.locator('.wk .week-appointment').count(),4);
      assert.equal(await card.getByRole('button',{name:'Ja, relevant',exact:true}).count(),0);
      assert.equal(await page.evaluate(()=>calls.filter(c=>c.service==='timetable_entry').slice(-2).map(c=>c.data.action).join(',')),'hide,confirm');

      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`PASS timetable additions ${width}px`);
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});

