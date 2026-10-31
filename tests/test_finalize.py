import importlib.util
from pathlib import Path
import pytest
from domain import RANK_LABELS, normalize_snapshot, comparable
spec=importlib.util.spec_from_file_location('finalize_collection',Path(__file__).resolve().parents[1]/'scripts/finalize_collection.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def candidate(ranks, week='2026-W44'):
    return {'week':week,'source':'qidian','books':[{'title':rt,'author':'A','url':'https://www.qidian.com/book/1/','rank_type':rt,'rank':1} for rt in ranks],
            'quality':{'rankings':{rt:{'requested':1,'status':'complete','reason':'requested_limit'} for rt in ranks}}}


def test_partial_and_fallback(tmp_path):
    ranks=list(RANK_LABELS)
    primary=candidate(ranks[:-1])
    assert module.finalize(primary,data_dir=tmp_path)=='partial'
    assert module.finalize(primary,candidate(ranks[-1:]),tmp_path)=='complete'
    assert module.finalize(primary,data_dir=tmp_path)=='not_published'


def test_empty_and_wrong_week(tmp_path):
    assert module.finalize(candidate([]),data_dir=tmp_path)=='not_published'
    assert not list(tmp_path.glob('*.json'))
    with pytest.raises(ValueError):
        module.finalize(candidate(['yuepiao']),candidate(['signnewbook'],'2026-W43'),tmp_path)


def test_definition_change_excludes_only_changed_ranking():
    before=normalize_snapshot(candidate(['yuepiao','signnewbook']))
    after=normalize_snapshot(candidate(['yuepiao','signnewbook']))
    after['quality']['rankings']['signnewbook']['definition_id']='signNewBkAll_v1'
    assert set(comparable(before,after)[2])=={'yuepiao'}

def test_incomplete_rank_cannot_be_spliced_into_publication(tmp_path):
    primary=candidate(['yuepiao','signnewbook'])
    primary['quality']['rankings']['signnewbook']['status']='partial'
    fallback=candidate(['signnewbook'])
    fallback['quality']['rankings']['signnewbook']['status']='partial'
    assert module.finalize(primary,fallback,tmp_path)=='partial'
    import json
    saved=json.loads((tmp_path/'2026-W44.json').read_text(encoding='utf-8'))
    assert {b['rank_type'] for b in saved['books']}=={'yuepiao'}
    assert saved['quality']['rankings']['signnewbook']['actual']==0


def test_primary_complete_rank_wins_as_a_whole(tmp_path):
    primary=candidate(['yuepiao'])
    fallback=candidate(['yuepiao'])
    fallback['books'][0]['title']='different observation'
    assert module.finalize(primary,fallback,tmp_path)=='partial'
    import json
    saved=json.loads((tmp_path/'2026-W44.json').read_text(encoding='utf-8'))
    assert saved['books'][0]['title']=='yuepiao'
