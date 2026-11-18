"""Archive sweeps must not change an initialized family's working inbox."""
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.util import dt as dt_util

from custom_components.eltern_portal_schulmanager.recovery import quarantine_archive_imports
from tests.test_schedule import manager
from tests.test_eltern_portal_schulmanager import _fake_result


async def test_full_archive_on_initialized_school_is_strictly_schedule_only(manager):
    m = manager
    today = dt_util.now().date()
    result = _fake_result(today, with_pdf=False)
    m.data['initialized'] = [result.school]
    known = result.children[0].items[0]
    m.children['anna'].update(school=result.school, student_id=result.children[0].student_id)
    m.items[known.uid] = {'uid':known.uid,'child':'anna','kind':known.kind,'title':known.title,
                          'sent':known.sent.isoformat(),'version':'old','body':'Old known content',
                          'read':True,'status':'erledigt','analysis':{'status':'fertig'},'files':[]}
    m.tasks['kept'] = {'id':'kept','child':'anna','item_uid':known.uid,'status':'erledigt',
                       'comment':'User note','source':'ki'}
    m.data['archived'] = {'anna':{'existing':'2026-11-01'}}
    baseline = deepcopy({k:m.data[k] for k in ('items','tasks','archived')})
    with patch.object(m, '_notify', new_callable=AsyncMock) as notify:
        await m._merge(result, archive_import=True)
    assert {k:m.data[k] for k in baseline} == baseline
    notify.assert_not_awaited()
    assert m.data['schedule_sources']
    assert not m._pending()
    await m._schedule_backfill()
    assert {k:m.data[k] for k in baseline} == baseline
    # Future normal fetches cannot introduce the same archived sources as new mail.
    result.children[0].items = [i for i in result.children[0].items if i.uid in m.data['schedule_sources']]
    await m._merge(result)
    assert {k:m.data[k] for k in baseline} == baseline


def test_recovery_preserves_preexisting_records_and_explicit_user_work():
    original = {'uid':'known','created':'2026-10-01T10:00:00+02:00','sent':'2020-01-01T10:00:00'}
    accidental = {'uid':'bad','created':'2026-11-18T10:42:00+01:00','sent':'2020-01-01T10:00:00','notify':True}
    recent = {'uid':'recent','created':'2026-11-18T10:42:00+01:00','sent':'2026-11-18T08:00:00'}
    data = {'items':{'known':original,'bad':accidental,'recent':recent,'invalid':{'created':'bad'}},
            'tasks':{'bad-auto':{'item_uid':'bad','source':'ki','status':'offen'},
                     'bad-edited':{'item_uid':'bad','source':'ki','status':'offen','comment':'Keep'},
                     'bad-done':{'item_uid':'bad','source':'ki','status':'erledigt'},
                     'manual':{'item_uid':'bad','source':'manuell','status':'offen'},
                     'known-task':{'item_uid':'known','source':'ki','status':'offen'}}}
    before = deepcopy(data)
    assert quarantine_archive_imports(data,120) == 1
    assert set(data['items']) == {'known','recent','invalid'}
    assert 'bad-auto' not in data['tasks']
    assert data['schedule_recovery']['items']['bad'] == before['items']['bad']
    assert data['schedule_recovery']['tasks']['bad-auto'] == before['tasks']['bad-auto']
    assert all(value == before['tasks'][key] for key,value in data['tasks'].items())
    assert quarantine_archive_imports(data,120) == 0


def test_recovery_handles_legacy_naive_and_missing_dates():
    data = {'items':{'legacy':{'uid':'legacy','created':'2026-11-18T12:00:00','sent':'2020-01-01'},
                     'missing':{}},'tasks':{}}
    assert quarantine_archive_imports(data,120) == 1
    assert 'missing' in data['items']
