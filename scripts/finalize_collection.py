"""Select whole validated rankings; never join pages from separate attempts."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scraper'))
from domain import DATA_DIR, RANK_LABELS, atomic_json, normalize_snapshot, now, build_index


def finalize(primary, fallback=None, data_dir=DATA_DIR):
    candidates = [normalize_snapshot(s) for s in (primary, fallback) if s]
    week = primary['week']
    if any(s['week'] != week or s['source'] != 'qidian' for s in candidates):
        raise ValueError('Candidate week or source mismatch')
    books, rankings = [], {}
    for rt in RANK_LABELS:
        selected = next((s for s in candidates if s['quality']['rankings'][rt]['status'] == 'complete'), None)
        if selected:
            books.extend(b for b in selected['books'] if b['rank_type'] == rt)
            rankings[rt] = selected['quality']['rankings'][rt]
        else:
            q = next((s['quality']['rankings'][rt] for s in reversed(candidates)
                      if s['quality']['rankings'][rt].get('collected_at')), candidates[0]['quality']['rankings'][rt])
            rankings[rt] = {**q, 'observed_count': q['actual'], 'actual': 0, 'status': 'missing',
                            'reason': q.get('reason', 'not_collected'),
                            'collected_at': q.get('collected_at', primary.get('scraped_at', now()))}
    complete = {rt for rt, q in rankings.items() if q['status'] == 'complete'}
    if not complete:
        return 'not_published'
    target = Path(data_dir) / (week + '.json')
    if target.exists():
        existing = normalize_snapshot(json.loads(target.read_text(encoding='utf-8')))
        previous = {rt for rt, q in existing['quality']['rankings'].items() if q['status'] == 'complete'}
        if not previous.issubset(complete):
            return 'not_published'
    snapshot = normalize_snapshot({'schema_version': 2, 'source': 'qidian', 'week': week,
                                   'scraped_at': now(), 'books': books, 'quality': {'rankings': rankings}})
    atomic_json(target, snapshot)
    atomic_json(Path(data_dir) / 'index.json', build_index(data_dir))
    return 'complete' if len(complete) == len(RANK_LABELS) else 'partial'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--primary', type=Path, required=True)
    parser.add_argument('--fallback', type=Path)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    args = parser.parse_args()
    primary = json.loads(args.primary.read_text(encoding='utf-8'))
    fallback = json.loads(args.fallback.read_text(encoding='utf-8')) if args.fallback and args.fallback.exists() else None
    result = finalize(primary, fallback, args.data_dir)
    print(result)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('publication=' + result + '\n')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('## Collection publication: ' + result + '\n')
    if result == 'not_published':
        sys.exit(1)
