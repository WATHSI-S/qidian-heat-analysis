"""Research workflow, privacy boundaries and evidence failures."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.app import create_app, parse_detail, CARD_FIELDS


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Path(__file__).resolve().parents[1] / 'data', tmp_path))


def test_roundtrip_and_restart(client, tmp_path):
    p = client.post('/api/projects', json={'name': '我的构思', 'idea': '修仙家族种田',
        'references': [{'title': '对标', 'author': '作者', 'intro': '主角经营家族',
                        'notes': {'核心设定': '我的判断'}, 'evidence': {'核心设定': '经营家族'}}],
        'card': {'决定': '调整', '下一步验证任务': '写两版简介'}}).json()
    backup = client.get(f"/api/projects/{p['id']}/export").json()
    restored = client.post('/api/import', json=backup).json()
    assert restored['id'] != p['id']
    assert restored['references'] == p['references']
    assert restored['card'] == p['card']
    restarted = TestClient(create_app(Path(__file__).resolve().parents[1] / 'data', tmp_path))
    assert len(restarted.get('/api/projects').json()) == 2
    md = client.get(f"/api/projects/{p['id']}/export?format=md").text
    assert '我的判断' in md and '经营家族' in md and '写两版简介' in md
    client.post('/api/catalog/refresh')
    assert client.get('/api/projects').json()[0]['card'] == p['card']


def test_local_security(client):
    assert client.post('/api/projects', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 403
    assert client.get('/private/workbench.sqlite3').status_code == 404
    assert client.post('/api/projects', json={'references': [{'title': 'x', 'url': 'http://127.0.0.1/'}]}).status_code == 422
    assert client.post('/api/import', json={'version': 1, 'project': None}).status_code == 422


def test_search_explains_and_does_not_fill_with_popular_books(client):
    assert client.get('/api/books?q=').json() == []
    assert client.get('/api/books?q=zzzzNONEXISTENT987654').json() == []
    rows = client.get('/api/books', params={'q': '修仙 家族 种田'}).json()
    assert rows and len(rows) <= 20
    assert all(r['matches'] and r['last_week'] for r in rows)
    assert all(rows[i]['score'] >= rows[i+1]['score'] for i in range(len(rows)-1))
    assert client.get('/api/books', params={'q': '修仙', 'category': '不存在的分类'}).json() == []


def test_failed_enrichment_and_ai_do_not_change_notes(client, monkeypatch):
    p = client.post('/api/projects', json={'references': [{'title': 'x', 'intro': '证据', 'notes': {'阅读期待': '笔记'}}]}).json()
    assert client.post(f"/api/projects/{p['id']}/references/0/enrich").status_code == 422
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert client.post(f"/api/projects/{p['id']}/suggest").status_code == 502
    assert client.get('/api/projects').json()[0]['references'] == p['references']


def test_detail_parser_does_not_guess_missing_fields():
    parsed = parse_detail('<div class="book-intro"><p>完整简介</p><p>第二段</p></div>')
    assert parsed['intro'] == '完整简介\n第二段'
    assert parsed['first_published'] is None and parsed['word_count'] is None
    with pytest.raises(ValueError):
        parse_detail('<html>访问验证</html>')


def test_ai_citations_are_validated_and_suggestions_are_not_applied(client, monkeypatch):
    from types import SimpleNamespace
    from analysis.ai_client import AIClient
    p = client.post('/api/projects', json={'references': [{'title': 'x', 'intro': '家族共同经营灵田'}], 'card': {'差异点': '个人内容'}}).json()
    calls = []
    def complete(self, **kwargs):
        calls.append(1)
        result = {'card': {k: '建议' for k in CARD_FIELDS}, 'citations': [{'index': 0, 'quote': '不存在的引用' if len(calls) == 1 else '经营灵田', 'claim': '经营题材'}]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    monkeypatch.setattr(AIClient, 'complete', complete)
    response = client.post(f"/api/projects/{p['id']}/suggest")
    assert response.status_code == 200 and len(calls) == 2
    assert response.json()['card']['决定'] == ''
    assert client.get('/api/projects').json()[0]['card']['差异点'] == '个人内容'
    assert client.post(f"/api/projects/{p['id']}/suggest").status_code == 200
    assert len(calls) == 2


def test_browser_research_flow(tmp_path):
    import socket
    import threading
    import time
    import uvicorn
    from playwright.sync_api import sync_playwright
    app = create_app(Path(__file__).resolve().parents[1] / 'data', tmp_path)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    base = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 375, 'height': 812}, reduced_motion='reduce')
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base)
            page.locator('#entrance').wait_for(state='visible')
            page.wait_for_function("document.querySelector('.entrance-art img').naturalWidth > 0")
            shots = Path(__file__).resolve().parents[1] / 'private' / 'previews'
            shots.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(shots / 'product-entrance.png'), full_page=True)
            page.emulate_media(reduced_motion='no-preference')
            page.mouse.move(400, 500)
            page.mouse.move(1200, 250, steps=15)
            page.wait_for_function("parseFloat(document.querySelector('#entrance').style.getPropertyValue('--tilt-y')) > 1")
            page.emulate_media(reduced_motion='reduce')
            page.locator('#enter-research').click()
            assert page.locator('#entrance').is_hidden()
            page.screenshot(path=str(shots / 'editorial-home.png'), full_page=True)
            page.locator('#new').click()
            page.locator('[data-field="idea"]').wait_for(state='visible')
            page.screenshot(path=str(shots / 'editorial-project.png'), full_page=True)
            page.set_viewport_size({'width': 375, 'height': 812})
            page.locator('[data-field="name"]').fill('种田构思')
            page.locator('[data-field="idea"]').fill('经营家族灵田')
            page.get_by_role('button', name='02 / 对标').click()
            page.get_by_text('手动加入榜单外作品').click()
            page.locator('#manualTitle').fill('人工对标')
            page.locator('#manualIntro').fill('家族经营灵田')
            page.locator('#manual').click()
            page.get_by_role('button', name='03 / 比较').click()
            page.locator('[data-note="核心设定"]').fill('我的素材优势')
            page.get_by_role('button', name='04 / 决定').click()
            page.locator('[data-card="差异点"]').fill('把农学经验写进去')
            page.locator('[data-card="决定"]').select_option('调整')
            page.locator('#save').click()
            page.wait_for_function("document.querySelector('#message').textContent === '已保存到本机'")
            page.reload()
            page.locator('#enter-research').click()
            page.locator('[data-project]').first.click()
            page.get_by_role('button', name='03 / 比较').click()
            assert page.locator('[data-note="核心设定"]').input_value() == '我的素材优势'
            page.get_by_role('button', name='04 / 决定').click()
            assert page.locator('[data-card="差异点"]').input_value() == '把农学经验写进去'
            page.locator('#return-entrance').click()
            page.screenshot(path=str(shots / 'product-entrance-mobile.png'), full_page=True)
            page.locator('#enter-market').click()
            market = page.frame_locator('#market-frame')
            market.locator('tbody [data-book]').first.click()
            market.get_by_role('button', name='加入选题对标', exact=True).click()
            market.get_by_role('button', name='去研究这本作品 →').click()
            page.locator('main').wait_for(state='visible')
            page.get_by_role('button', name='03 / 比较').click()
            assert page.locator('#editor details.book').count() == 2
            assert not errors
            page.screenshot(path=str(shots / 'editorial-mobile.png'), full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
