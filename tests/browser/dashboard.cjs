// Run with Node and Playwright installed; uses system Chromium, no portal access.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox']});
  try {
    for (const width of [1280, 390]) {
      const page = await browser.newPage({timezoneId:"UTC", viewport: {width, height: 900}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.setContent('<!doctype html><html lang="de"><body></body></html>');
      await page.addScriptTag({path: path.resolve(__dirname, '../../custom_components/eltern_portal_schulmanager/www/eltern-portal-schulmanager-card.js')});
      await page.evaluate(() => {
        const data = {today: '2026-11-05', version: '0.14.4', last_update: '2026-11-05T12:34:00Z', children: [{key:'mireia',name:'Mireia',timetable:[{weekday:2,lesson:'1',subject:'M',room:'101',teacher:'AB',teacher_label:'AB (Anna Beispiel)',start:'08:00',end:'08:45'}],substitutions:{available:true,days:[{date:'2026-11-10',entries:[{uid:'sub1',lesson:'1',kind:'vertretung',teacher_label:'AB (Anna Beispiel)',substitute_label:'CD (Clara Demo)',room:'202',info:'Buch mitbringen'}]}]},events:[{uid:'vertretung-sub1',date:'2026-11-10',category:'vertretung',title:'Mathematik',child:'mireia',links:{ics:'/test.ics'}}]}]};
        window.calls = [];
        window.fixture = data;
        for (const [tag, cfg] of [['stundenplan',{child:'mireia',view:'week'}],['header',{}],['termine',{child:'mireia'}]]) {
          const card = document.createElement('eltern-portal-schulmanager-' + tag);
          card.setConfig(cfg);
          card._data = data;
          card._hass = {user:{is_admin:true},callService:async (...args)=>window.calls.push(args),callWS:async ()=>({ics:"/test.ics"})};
          card._subscribe = () => {};
          card._load = async () => {};
          document.body.append(card);
          card._render();
        }
      });
      const plan = page.locator('eltern-portal-schulmanager-stundenplan');
      await plan.getByRole('button',{name:'Woche vor',exact:true}).click();
      const lesson = plan.locator('[data-lesson]');
      await lesson.focus();
      await page.keyboard.press('Enter');
      await plan.locator('.lesson-selected').waitFor();
      const text = await plan.locator("ha-card").innerText();
      assert.match(text,/10\.11\./);
      assert.match(text,/Anna Beispiel/);
      assert.match(text,/Vertretungslehrkraft: CD \(Clara Demo\)/);
      assert.match(text,/101 → 202/);
      assert.match(text,/Buch mitbringen/);
      await plan.locator('[data-cal]').click();
      await plan.getByRole('link',{name:/In Kalender eintragen/}).waitFor({timeout:2000});
      await plan.getByRole('button',{name:'Woche',exact:true}).click();
      assert.equal(await plan.locator('[data-date="2026-11-10"]').count(),1);
      for (const kind of ['entfall', 'raum', null]) {
        await plan.evaluate((card, kind) => {
          const child = card._data.children[0];
          child.substitutions.days[0].entries = kind ? [{lesson:'1',kind,room:kind === 'raum' ? '303' : '',info:''}] : [];
          card._week = {mireia:false};
          card._render();
        }, kind);
        const details = await plan.locator('ha-card').innerText();
        assert.match(details, kind === 'entfall' ? /Status: entfällt/ : kind === 'raum' ? /101 → 303/ : /Status: regulärer Unterricht/);
      }
      await plan.evaluate(card => {
        const lesson = card._data.children[0].timetable[0];
        lesson.optional = true;
        lesson.participation = 'not_registered';
        lesson.teacher_source = {title:'Förderangebote 2026/2027',sent:'2026-09-15',url:'https://example.org/course-source'};
        card._render();
      });
      assert.match(await plan.locator('ha-card').innerText(), /Optional · nicht angemeldet/);
      assert.match(await plan.locator('ha-card').innerText(), /Status: optionales Klassenangebot/);
      assert.equal(await plan.getByRole('link', {name:'Förderangebote 2026/2027'}).getAttribute('href'), 'https://example.org/course-source');
      for (const [state, label] of [['registered','angemeldet'],['unknown','Teilnahme ungeklärt']]) {
        await plan.evaluate((card,state) => {card._data.children[0].timetable[0].participation=state;card._render();}, state);
        assert.match(await plan.locator('ha-card').innerText(), new RegExp('Optional · '+label));
      }
      await plan.getByRole('button',{name:'Woche',exact:true}).click();
      assert.match(await plan.locator('[data-lesson]').innerText(), /Teilnahme ungeklärt/);
      // WebUntis can supply timed changes without any portal timetable.
      await plan.evaluate(card => {
        const child = card._data.children[0];
        child.timetable = [];
        child.substitutions.days[0].entries = [{kind:'raum',subject:'Biologie',lesson:'',
          start:'2026-11-10T10:15:00Z',end:'2026-11-10T11:00:00Z',
          original_room:'101',room:'303',source:'webuntis'}];
        card._render();
      });
      assert.match(await plan.locator('ha-card').innerText(), /Weitere Änderungen/i);
      assert.match(await plan.locator('ha-card').innerText(), /101 → 303/);
      await plan.getByRole('button',{name:'Woche',exact:true}).click();
      assert.match(await plan.locator('ha-card').innerText(), /10:15/);
      assert.match(await plan.locator('ha-card').innerText(), /Biologie/);
      const footer = page.locator('eltern-portal-schulmanager-header');
      assert.equal(await footer.locator('.ttl, img, .sub').count(),0);
      assert.match(await footer.locator("ha-card").innerText(),/Stand:.*12:34/);
      assert.match(await footer.locator("ha-card").innerText(),/v0\.14\.4/);
      await footer.getByRole('button',{name:'Portale jetzt abrufen'}).click();
      assert.equal(await page.evaluate(()=>calls[0][1]),'refresh');
      assert.match(await footer.getByRole('link',{name:'⚙️ Einstellungen'}).getAttribute('href'),/config\/integrations/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false);
      const agenda = page.locator('eltern-portal-schulmanager-termine');
      const archive = agenda.getByRole('button',{name:'Ins Archiv verschieben',exact:true});
      assert.equal(await archive.innerText(),'×');
      await archive.click();
      assert.equal(await page.evaluate(()=>calls.at(-1)[1]),'archive_event');
      await agenda.getByRole('button',{name:/Archiv/}).click();
      await agenda.getByRole('button',{name:'Reaktivieren',exact:true}).click();
      assert.equal(await page.evaluate(()=>calls.at(-1)[1]),'unarchive_event');
      assert.deepEqual(errors,[]);
      await page.screenshot({path:`/tmp/schulmanager-${width}.png`,fullPage:true});
      await page.close();
      console.log(`PASS Chromium ${width}px: Mireia, selected date, keyboard, teachers, room, calendar, WebUntis without timetable, footer`);
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
