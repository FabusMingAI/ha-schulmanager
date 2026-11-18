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
      assert.equal(await card.getByRole('button',{name:'Übernehmen',exact:true}).count(),0);
      await card.locator('[data-schedule-open]').filter({hasText:'Robotikkurs'}).click();
      assert.equal(await card.getByRole('link',{name:'Kursangebot'}).getAttribute('href'),'https://example.org/course');
      await card.getByRole('button',{name:'Übernehmen',exact:true}).click();
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
      assert.equal(await card.locator('table [data-schedule-open]').filter({hasText:'Robotikkurs'}).count(),1);
      assert.equal(await card.locator('table').locator('[data-schedule-action]').count(),0);
      await card.getByRole('button',{name:'Woche vor',exact:true}).click();
      assert.match(await card.locator('ha-card').innerText(),/Weihnachtsferien/);
      assert.doesNotMatch(await card.locator('ha-card').innerText(),/Robotikkurs/);
      assert.equal(await card.locator('[data-lesson]').count(),0);
      await card.getByRole('button',{name:'Ferien an',exact:true}).click();
      assert.equal(await card.locator('[data-lesson]').count(),1);
      await card.getByRole('button',{name:'Woche zurück',exact:true}).click();
      await card.getByRole('button',{name:'Woche zurück',exact:true}).click();
      assert.match(await card.locator('ha-card').innerText(),/Archiv-Ausflug/);
      await card.getByRole('button',{name:'Archiv erneut prüfen'}).click();
      assert.equal(await page.evaluate(()=>calls.at(-1).service),'rescan_schedule');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`PASS timetable additions ${width}px`);
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});

