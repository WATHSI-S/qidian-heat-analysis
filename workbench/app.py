"""Local research API. Never mounted by the public site builder."""
import hashlib
import json
import re
import sqlite3
import sys
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scraper'))
from domain import load_weeks, book_key, book_url, now

CARD_FIELDS = ['一句话卖点', '目标读者', '参考点', '差异点', '写作优势', '最大不确定因素', '决定', '下一步验证任务']
DIMENSIONS = ['阅读期待', '主角目标', '主要阻力', '核心设定', '简介卖点', '保留与改变', '素材优势与疑问']


class Reference(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default='', max_length=200)
    category: str = Field(default='', max_length=200)
    status: str = Field(default='', max_length=100)
    url: str | None = None
    intro: str = Field(default='', max_length=20000)
    source: str = Field(default='manual', max_length=1000)
    collected_at: str = ''
    last_week: str = ''
    newbook: bool = False
    complete: bool = False
    word_count: str | None = None
    first_published: str | None = None
    notes: dict[str, str] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)


class Project(BaseModel):
    name: str = Field(default='未命名选题', max_length=200)
    idea: str = Field(default='', max_length=4000)
    category: str = Field(default='', max_length=200)
    experience: str = Field(default='', max_length=4000)
    strengths: str = Field(default='', max_length=4000)
    avoid: str = Field(default='', max_length=2000)
    references: list[Reference] = Field(default_factory=list, max_length=5)
    card: dict[str, str] = Field(default_factory=dict)
    ai_suggestion: dict = Field(default_factory=dict)


def parse_detail(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    intro = soup.select_one('.book-intro')
    if intro is None or not intro.get_text(strip=True):
        raise ValueError('详情页未提供可识别的完整简介，请手动补录')
    info = soup.select_one('.book-info')
    tags = info.select('.tag a') if info else []
    words = info.select_one('.count') if info else None
    # Dates are only taken from explicitly named metadata, never inferred from updates.
    published = soup.select_one('meta[itemprop="datePublished"]')
    return dict(intro=intro.get_text('\n', strip=True), complete=True,
                category=' / '.join(t.get_text(strip=True) for t in tags) or '',
                word_count=words.get_text(' ', strip=True) if words else None,
                first_published=published.get('content') if published else None)


def create_app(data_dir=ROOT / 'data', private_dir=ROOT / 'private'):
    app = FastAPI(docs_url=None, redoc_url=None)
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    db = private_dir / 'workbench.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT, updated TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT)')
    catalog = []
    detail_lock = threading.Lock()

    def refresh():
        books = {}
        for week in load_weeks(data_dir):
            for b in week['books']:
                key = book_key(b)
                old = books.get(key)
                same_week = old and old['last_week'] == week['week']
                books[key] = dict(title=b['title'], author=b['author'], category=b['category'],
                                  status=b.get('status', ''), intro=b.get('intro', ''),
                                  url=b.get('url') or (old or {}).get('url'), source='ranking',
                                  last_week=week['week'], collected_at=week.get('scraped_at', ''),
                                  complete=False, newbook=b['rank_type'] == 'signnewbook' or
                                  bool(same_week and old['newbook']))
        catalog[:] = books.values()
        return {'books': len(catalog)}

    refresh()

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host', '').split(':')[0]
        origin = request.headers.get('origin')
        if host not in ('127.0.0.1', 'localhost', 'testserver'):
            return Response('Invalid host', status_code=403)
        if request.method not in ('GET', 'HEAD') and (
            origin and origin != f'{request.url.scheme}://{request.headers.get("host")}' or
            request.headers.get('sec-fetch-site') == 'cross-site'
        ):
            return Response('Cross-site write rejected', status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def read(pid):
        with sqlite3.connect(db) as conn:
            row = conn.execute('SELECT body FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            raise HTTPException(404, '项目不存在')
        return json.loads(row[0])

    def cache_get(key):
        with sqlite3.connect(db) as conn:
            row = conn.execute('SELECT body FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(key, value):
        with sqlite3.connect(db) as conn:
            conn.execute('INSERT OR REPLACE INTO cache VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

    @app.get('/api/projects')
    def projects():
        with sqlite3.connect(db) as conn:
            return [dict(id=r[0], **json.loads(r[1]), updated_at=r[2]) for r in conn.execute(
                'SELECT id,body,updated FROM projects ORDER BY updated DESC')]

    @app.post('/api/projects')
    def create(project: Project):
        return save(str(uuid.uuid4()), project)

    @app.put('/api/projects/{pid}')
    def save(pid: str, project: Project):
        for ref in project.references:
            if ref.url:
                ref.url = book_url(ref.url)
                if not ref.url:
                    raise HTTPException(422, '仅支持起点作品链接')
        with sqlite3.connect(db) as conn:
            conn.execute('INSERT OR REPLACE INTO projects VALUES (?,?,?)',
                         (pid, project.model_dump_json(), now()))
        return dict(id=pid, **project.model_dump())

    @app.post('/api/catalog/refresh')
    def reload_catalog():
        return refresh()

    @app.post('/api/projects/{pid}/from-ranking')
    def from_ranking(pid: str, selected: Reference):
        project = Project(**read(pid))
        book = next((b for b in catalog if book_key(b) == book_key(selected.model_dump())), None)
        if not book:
            raise HTTPException(404, '本地书目中没有这本作品，请刷新本地书目')
        if any(book_key(r.model_dump()) == book_key(book) for r in project.references):
            raise HTTPException(409, '这本作品已经在当前选题中')
        if len(project.references) >= 5:
            raise HTTPException(422, '每个选题最多选择 5 本对标作品')
        project.references.append(Reference(**book))
        return save(pid, project)

    @app.get('/api/books')
    def search(q: str = '', category: str = '', status: str = '', newbook: bool = False):
        import jieba
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        from analysis.text_mining import WEB_NOVEL_TERMS, STOP_WORDS
        for term in WEB_NOVEL_TERMS:
            jieba.add_word(term)
        rows = [b for b in catalog if (not category or category in b['category']) and
                (not status or status in b['status']) and (not newbook or b['newbook'])]
        if not q.strip() or not rows:
            return []
        tokenize = lambda s: [t for t in jieba.lcut(s) if t.strip() and t not in STOP_WORDS]
        vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None)
        try:
            matrix = vectorizer.fit_transform([f"{b['title']} {b['category']} {b['intro']}" for b in rows])
        except ValueError:
            return []
        scores = cosine_similarity(vectorizer.transform([q[:6000]]), matrix)[0]
        terms = set(tokenize(q))
        return [dict(**rows[i], score=round(float(scores[i]), 4),
                     matches=sorted(terms.intersection(tokenize(rows[i]['intro'] + rows[i]['title'] + rows[i]['category']))))
                for i in sorted(range(len(rows)), key=lambda i: -scores[i])[:20] if scores[i] > 0]

    @app.post('/api/projects/{pid}/references/{index}/enrich')
    def enrich(pid: str, index: int):
        project = Project(**read(pid))
        if not 0 <= index < len(project.references):
            raise HTTPException(404, '作品不存在')
        ref = project.references[index]
        url = book_url(ref.url)
        if not url:
            raise HTTPException(422, '请先填写有效起点作品链接')
        with detail_lock:
            result = cache_get('detail:' + url)
            if result is None:
                from playwright.sync_api import sync_playwright
                from tenacity import Retrying, stop_after_attempt, wait_fixed
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        try:
                            page = browser.new_page()
                            # Do not follow arbitrary external redirects from a supplied URL.
                            page.route('**/*', lambda route: route.continue_() if
                                       route.request.url.startswith('https://www.qidian.com/') else route.abort())
                            for attempt in Retrying(stop=stop_after_attempt(2), wait=wait_fixed(3), reraise=True):
                                with attempt:
                                    response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                                    if not response or response.status != 200:
                                        raise ValueError('源站访问未成功')
                                    page.wait_for_selector('.book-intro', timeout=10000)
                                    result = dict(**parse_detail(page.content()), source=url, collected_at=now())
                        finally:
                            browser.close()
                    cache_put('detail:' + url, result)
                except Exception:
                    raise HTTPException(502, '详情读取失败，已有材料已保留；请手动粘贴完整简介')
            for k, v in result.items():
                if v is not None and v != '':
                    setattr(ref, k, v)
        return save(pid, project)

    @app.get('/api/projects/{pid}/export')
    def export(pid: str, format: str = 'json'):
        project = read(pid)
        if format == 'json':
            return Response(json.dumps(dict(version=1, project=project), ensure_ascii=False, indent=2),
                            media_type='application/json', headers={'Content-Disposition': 'attachment; filename="research.json"'})
        lines = ['# ' + project['name']]
        for key in ('idea', 'category', 'experience', 'strengths', 'avoid'):
            lines.extend(['', f'## {dict(idea="构思",category="分类",experience="阅读体验",strengths="素材优势",avoid="避免元素")[key]}', project[key]])
        for k in CARD_FIELDS:
            lines.extend(['', '## ' + k, project['card'].get(k, '')])
        for c in project.get('ai_suggestion', {}).get('citations', []):
            lines.extend(['', '### AI 建议依据（请人工核对）',
                          f"{c.get('title', '')}：{c.get('quote', '')}", c.get('claim', '')])
        for ref in project['references']:
            lines.extend(['', '## 对标：' + ref['title'], f"作者：{ref['author']}；来源：{ref['source']}；时间：{ref['collected_at']}", ref.get('url') or '', ref['intro']])
            for dim in DIMENSIONS:
                lines.extend([f'### {dim}', '简介证据：' + ref['evidence'].get(dim, ''), '个人笔记：' + ref['notes'].get(dim, '')])
        return Response('\n'.join(lines), media_type='text/markdown', headers={'Content-Disposition': 'attachment; filename="research.md"'})

    @app.post('/api/import')
    def import_project(payload: dict):
        if payload.get('version') != 1:
            raise HTTPException(422, '不支持的备份版本')
        try:
            project = Project.model_validate(payload.get('project'))
        except ValueError:
            raise HTTPException(422, '备份内容无效')
        return create(project)

    @app.post('/api/projects/{pid}/suggest')
    def suggest(pid: str):
        from analysis.ai_client import AIClient, MODEL
        project = read(pid)
        if not project['references']:
            raise HTTPException(422, '请先选择对标作品')
        project.pop('ai_suggestion', None)
        material = json.dumps(project, ensure_ascii=False)
        key = 'ai:v1:' + MODEL + hashlib.sha256(material.encode()).hexdigest()
        cached = cache_get(key)
        if cached:
            return cached
        messages = [{'role': 'system', 'content': '根据提供的构思及材料生成选题卡。不要预测成功率或从简介猜开篇/后期剧情。缺证据留空。只输出JSON：card对象的键为' + '、'.join(CARD_FIELDS) + '，值为字符串；citations列表每项包含index(作品从0编号)、quote(简介原文片段)、claim(支持的判断)。决定留空交给作者。'},
                    {'role': 'user', 'content': material}]
        try:
            client = AIClient(max_calls=2, token_budget=80000)
            for attempt in range(2):
                response = client.complete(messages=messages, response_format={'type': 'json_object'}, max_tokens=3000)
                try:
                    result = json.loads(response.choices[0].message.content)
                    assert set(result['card']) == set(CARD_FIELDS)
                    assert all(isinstance(v, str) for v in result['card'].values())
                    assert result['citations']
                    for c in result['citations']:
                        assert isinstance(c['index'], int) and 0 <= c['index'] < len(project['references'])
                        assert c['quote'] and c['quote'] in project['references'][c['index']]['intro']
                        assert isinstance(c['claim'], str)
                        c['title'] = project['references'][c['index']]['title']
                    result['card']['决定'] = ''
                    cache_put(key, result)
                    return result
                except (ValueError, KeyError, TypeError, AssertionError):
                    messages.append({'role': 'user', 'content': '格式或原文引用不正确，请严格按要求修正；引用必须来自作品简介。'})
            raise ValueError('invalid response')
        except Exception:
            raise HTTPException(502, 'AI 暂不可用或证据验证未通过，个人内容未改变')

    @app.get('/')
    def home():
        return FileResponse(Path(__file__).parent / 'static/index.html')

    @app.get('/market/')
    @app.get('/market/index.html')
    def market():
        path = ROOT / 'dist/site/index.html'
        if not path.exists():
            return Response('请先运行 python scripts/build_site.py 构建榜单页面，再刷新。', status_code=503)
        html = path.read_text(encoding='utf-8').replace('</head>',
            '<link rel="stylesheet" href="/static/market.css"></head>')
        html = html.replace('</body>', '<script type="module" src="/static/market-bridge.js"></script></body>')
        return Response(html, media_type='text/html')

    app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')
    app.mount('/market', StaticFiles(directory=ROOT / 'dist/site', check_dir=False), name='market')
    return app


app = create_app()
