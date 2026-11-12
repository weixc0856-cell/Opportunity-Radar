"""YouTube interviews as an opt-in source of fresh, primary-source transcripts.

The collector is deliberately separate from the FreshRSS path:

* It only reads public metadata and the creator/auto subtitles. It never downloads the
  video, never uses cookies, never bypasses a login or a paywall, and never asks YouTube
  for a Chinese auto-translation.
* A YouTube video becomes one article whose `summary` is a bounded, keyword-selected
  transcript excerpt. The full transcript stays in `data/youtube/<video_id>/` for
  traceability; the business database stores only metadata and the excerpt.
* Evidence remains capped at E1 ("subtitle quote located") because an auto-caption is not
  a reviewed full text and may mis-hear the speaker. The report labels the subtitle kind.
* The source registry is local and opt-in (`config/youtube_sources.json`); the tracked
  example is disabled. No channel is scraped until a reviewer enables it.

This module uses only the standard library. yt-dlp is an external executable, resolved
from `OR_YTDLP` (default: the YouTube-B virtualenv on this machine) or PATH.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from .freshrss_client import Article
from .source_policy import Source

DEFAULT_CONFIG = Path('config/youtube_sources.json')
EXAMPLE_CONFIG = Path('config/youtube_sources.example.json')
DEFAULT_YTDLP = Path('E:/YouTube-B/.venv/Scripts/yt-dlp.exe')
YOUTUBE_TERMS = 'https://www.youtube.com/t/terms'

# Terms that usually carry a commercial signal in an interview. They only decide which
# slice of a long transcript is worth analysing; the model still has to quote evidence.
SIGNAL_KEYWORDS = (
    'price', 'pricing', 'cost', 'budget', 'spend', 'contract', 'procurement', 'purchase',
    'revenue', 'margin', 'roi', 'payback', 'customer', 'client', 'enterprise', 'buyer',
    'deploy', 'deployment', 'migration', 'bottleneck', 'outage', 'downtime', 'capacity',
    'shortage', 'hiring', 'regulation', 'compliance', 'market size', 'tam', 'sam', 'som',
    'subscription', 'license', 'per seat', 'saving', 'savings', 'investment', 'funding',
    '价格', '成本', '预算', '采购', '合同', '收入', '毛利', '客户', '企业', '部署', '迁移',
    '瓶颈', '停机', '容量', '短缺', '招聘', '监管', '合规', '市场规模', '订阅', '许可',
)
COMMERCIAL_DEFAULT = {'price', 'pricing', 'budget', 'procurement', 'contract', 'revenue',
                      'margin', 'customer', 'enterprise', 'buyer', '采购', '预算', '客户',
                      '合同', '收入', '毛利', '价格'}
CUE_TIMESTAMP = re.compile(
    r'(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{3})')
TAG = re.compile(r'<[^>]+>')
MUSIC = re.compile(r'^\[(?:music|applause|laughter|silence|foreign)\].*$', re.I)


class YouTubeUnavailable(RuntimeError):
    """The optional collector cannot run; the daily digest must continue without it."""


@dataclass
class YouTubeArticle(Article):
    source_id: str = ''
    youtube: dict | None = None


def ytdlp_path() -> Path:
    configured = os.environ.get('OR_YTDLP')
    if configured:
        path = Path(configured)
        if path.exists():
            return path
        raise YouTubeUnavailable(f'OR_YTDLP does not exist: {path}')
    if DEFAULT_YTDLP.exists():
        return DEFAULT_YTDLP
    for name in ('yt-dlp.exe', 'yt-dlp'):
        found = _which(name)
        if found:
            return Path(found)
    raise YouTubeUnavailable('yt-dlp not found; set OR_YTDLP or install yt-dlp')


def _which(name: str) -> str:
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return ''


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise YouTubeUnavailable(f'yt-dlp timed out after {timeout}s: {cmd[-1]}') from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        raise YouTubeUnavailable(f'yt-dlp failed ({result.returncode}): {detail[-800:]}')
    return result


def _json(cmd: list[str], timeout: int = 180) -> dict:
    out = _run(cmd, timeout).stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise YouTubeUnavailable(f'yt-dlp returned invalid JSON: {exc}') from exc


def load_config(path=None) -> dict:
    """Load and normalise the opt-in registry. A missing file means "no YouTube"."""
    target = Path(path or os.environ.get('OR_YOUTUBE_CONFIG') or DEFAULT_CONFIG)
    if not target.exists():
        return {'enabled': False, 'sources': [], 'config_path': str(target), 'missing': True}
    try:
        raw = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'enabled': False, 'sources': [], 'config_path': str(target),
                'issues': [{'severity': 'error', 'code': 'youtube_config_invalid',
                            'message': f'{type(exc).__name__}: {exc}'}]}
    if not isinstance(raw, dict):
        return {'enabled': False, 'sources': [], 'config_path': str(target),
                'issues': [{'severity': 'error', 'code': 'youtube_config_invalid',
                            'message': 'config must be a JSON object'}]}
    config = dict(raw)
    env_flag = os.environ.get('OR_YOUTUBE_ENABLED', '').strip().lower() in {'1','true','yes','on'}
    config['enabled'] = bool(raw.get('enabled')) and env_flag
    config['config_path'] = str(target)
    config['missing'] = False
    config.setdefault('max_videos_per_day', 3)
    config.setdefault('max_transcript_chars', 6000)
    config.setdefault('max_age_days', 14)
    config.setdefault('languages', ['en'])
    config.setdefault('require_signal', True)
    config.setdefault('impersonate', 'chrome')
    config.setdefault('min_duration', 300)
    config.setdefault('max_duration', 10800)
    sources = raw.get('sources') if isinstance(raw.get('sources'), list) else []
    config['sources'] = [s for s in sources if isinstance(s, dict)]
    issues = list(config.get('issues') or [])
    for source in config['sources']:
        issues.extend(_validate_source(source))
    config['issues'] = issues
    return config


def _validate_source(source: dict) -> list[dict]:
    issues = []
    sid = str(source.get('source_id') or '').strip()
    name = str(source.get('name') or '').strip()
    if not sid:
        issues.append({'severity': 'error', 'code': 'youtube_missing_source_id',
                       'message': 'source_id is required'})
    if not name:
        issues.append({'severity': 'error', 'code': 'youtube_missing_name',
                       'message': f'{sid or "(unknown)"}: name is required', 'source_id': sid})
    targets = [source.get('channel_url'), source.get('video_url'), source.get('search_query')]
    if not any(str(t or '').strip() for t in targets):
        issues.append({'severity': 'error', 'code': 'youtube_missing_target',
                       'message': f'{sid or "(unknown)"}: set channel_url, video_url or search_query',
                       'source_id': sid})
    if source.get('enabled') and str(source.get('permission_status') or '') != 'approved':
        issues.append({'severity': 'error', 'code': 'youtube_not_approved',
                       'message': f'{sid}: enabled sources must have permission_status=approved',
                       'source_id': sid})
    return issues


def enabled_sources(config: dict) -> list[dict]:
    if not config.get('enabled'):
        return []
    return [s for s in config.get('sources') or []
            if s.get('enabled') and str(s.get('permission_status') or '') == 'approved']


def source_objects(config: dict) -> list[Source]:
    """Synthetic registry rows so scoring, caps and lineage see a real source."""
    out = []
    for s in enabled_sources(config):
        sid = str(s.get('source_id') or '')
        url = str(s.get('channel_url') or s.get('video_url') or s.get('search_query') or '')
        if not sid:
            continue
        out.append(Source(
            source_id=sid, name=str(s.get('name') or sid), homepage=url, feed_url=url,
            access_method='youtube_transcript', permission_status='approved', enabled=True,
            freshrss_feed_id='', source_type='youtube',
            provenance_class=str(s.get('provenance_class') or 'first_party'),
            canonical_domain='youtube.com', terms_url=str(s.get('terms_url') or YOUTUBE_TERMS),
            last_verified_at=str(s.get('last_verified_at') or ''),
            reviewed_at=str(s.get('reviewed_at') or ''),
            editorial_lanes=str(s.get('editorial_lanes') or 'A,B,C'),
            topic_tags=str(s.get('topic_tags') or ''), source_authority=str(s.get('source_authority') or ''),
            content_access_level='excerpt', source_cap=_cap(s.get('source_cap', 1)),
            intelligence_lines=str(s.get('intelligence_lines') or ''),
            full_text_fetch='none'))
    return out


def _cap(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _published(entry: dict) -> str:
    raw = entry.get('timestamp') or entry.get('release_timestamp')
    if raw:
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).date().isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    text = str(entry.get('upload_date') or '')
    if re.fullmatch(r'\d{8}', text):
        return f'{text[:4]}-{text[4:6]}-{text[6:]}'
    return ''


def _age_days(published: str) -> int | None:
    if not published:
        return None
    try:
        return (datetime.now(timezone.utc).date() - datetime.fromisoformat(published).date()).days
    except ValueError:
        return None


def _candidate_entries(source: dict, config: dict) -> list[dict]:
    url = str(source.get('video_url') or '').strip()
    if url:
        return [_json([str(ytdlp_path()), '--dump-single-json', '--skip-download',
                       '--no-warnings', '--no-playlist', url])]
    if source.get('search_query'):
        target = f"ytsearch{int(source.get('max_candidates', 8))}:{source['search_query']}"
    else:
        target = str(source.get('channel_url') or '')
    if not target.startswith(('https://', 'ytsearch')):
        raise YouTubeUnavailable(f"{source.get('source_id')}: target must be an HTTPS YouTube URL")
    data = _json([str(ytdlp_path()), '--flat-playlist', '--dump-single-json',
                  '--playlist-end', str(int(source.get('max_candidates', 12))),
                  '--no-warnings', target])
    return list(data.get('entries') or [])


def _source_matches(entry: dict, source: dict, config: dict) -> tuple[bool, str]:
    title = str(entry.get('title') or '')
    keywords = [str(k).lower() for k in source.get('keywords') or [] if str(k).strip()]
    if keywords and not any(k in title.lower() for k in keywords):
        return False, 'title_keywords'
    if str(entry.get('live_status') or '') in {'is_live', 'is_upcoming'}:
        return False, 'live_or_upcoming'
    duration = entry.get('duration')
    if isinstance(duration, (int, float)):
        if duration < int(source.get('min_duration', config.get('min_duration', 300))):
            return False, 'too_short'
        if duration > int(source.get('max_duration', config.get('max_duration', 10800))):
            return False, 'too_long'
    published = _published(entry)
    age = _age_days(published)
    limit = int(source.get('max_age_days', config.get('max_age_days', 14)))
    if age is not None and age > limit:
        return False, 'too_old'
    return True, ''


def plan_candidates(config: dict, store=None) -> tuple[list[dict], dict, list[dict]]:
    """Return selected candidates, counters and config issues without downloading subtitles."""
    counters = {'sources': 0, 'candidates': 0, 'selected': 0, 'skipped_seen': 0,
                'skipped_filter': 0, 'skipped_reason': {}}
    issues = list(config.get('issues') or [])
    selected = []
    if not config.get('enabled'):
        return selected, counters, issues
    try:
        ytdlp_path()
    except YouTubeUnavailable as exc:
        issues.append({'severity': 'warning', 'code': 'youtube_unavailable', 'message': str(exc)})
        return selected, counters, issues
    budget = int(config.get('max_videos_per_day', 3))
    for source in enabled_sources(config):
        if len(selected) >= budget:
            break
        counters['sources'] += 1
        try:
            entries = _candidate_entries(source, config)
        except YouTubeUnavailable as exc:
            issues.append({'severity': 'warning', 'code': 'youtube_list_failed',
                           'source_id': source.get('source_id'), 'message': str(exc)[:500]})
            continue
        seen_this_source = 0
        for entry in entries:
            counters['candidates'] += 1
            ok, reason = _source_matches(entry, source, config)
            if not ok:
                counters['skipped_filter'] += 1
                counters['skipped_reason'][reason] = counters['skipped_reason'].get(reason, 0) + 1
                continue
            video_id = str(entry.get('id') or '').strip()
            if not video_id:
                continue
            if store is not None and store.youtube_video_seen(video_id):
                counters['skipped_seen'] += 1
                continue
            selected.append({'source': source, 'entry': entry, 'video_id': video_id})
            counters['selected'] += 1
            seen_this_source += 1
            per_source = _cap(source.get('source_cap', 1))
            if per_source and seen_this_source >= per_source:
                break
            if len(selected) >= budget:
                break
    return selected, counters, issues


def parse_vtt(text: str) -> list[tuple[float, float, str]]:
    """Parse WebVTT into (start, end, text). Cue settings and inline tags are discarded."""
    clean = text.replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    lines = clean.split('\n')
    index = 0
    while index < len(lines):
        match = CUE_TIMESTAMP.search(lines[index])
        if not match:
            index += 1
            continue
        start = _seconds(match, 1, 2, 3, 4)
        end = _seconds(match, 5, 6, 7, 8)
        index += 1
        body = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        spoken = _clean_cue(' '.join(body))
        if spoken and not MUSIC.match(spoken):
            cues.append((start, max(end, start + 0.2), spoken))
    return _dedupe(cues)


def _seconds(match, hours, minutes, seconds, millis) -> float:
    h = int(match.group(hours) or 0)
    return h * 3600 + int(match.group(minutes)) * 60 + int(match.group(seconds)) + int(match.group(millis)) / 1000


def _clean_cue(text: str) -> str:
    text = unescape(TAG.sub(' ', text))
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _dedupe(cues: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    out = []
    for start, end, text in cues:
        if out and text == out[-1][2]:
            out[-1] = (out[-1][0], max(out[-1][1], end), text)
        else:
            out.append((start, end, text))
    return out


def _stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f'{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}'


def select_excerpt(cues: list[tuple[float, float, str]], max_chars: int = 6000,
                   keywords=None, require_signal: bool = True) -> dict:
    """Pick the densest commercial window of a long transcript.

    The window is contiguous and bounded; the full transcript stays on disk. This keeps
    the analysis input comparable to an article summary and avoids feeding a one-hour
    interview into a model that was designed for a 7 KB excerpt.
    """
    words = {str(k).lower() for k in (keywords or SIGNAL_KEYWORDS)}
    blocks = _blocks(cues)
    if not blocks:
        return {'text': '', 'start': 0.0, 'end': 0.0, 'score': 0, 'reason': 'empty_transcript'}
    scored = []
    for start, end, text in blocks:
        lower = text.lower()
        score = sum(3 if w in COMMERCIAL_DEFAULT else 1 for w in words if w and w in lower)
        scored.append((start, end, text, score))
    best = None
    for i in range(len(scored)):
        chars = 0; total = 0; j = i
        while j < len(scored) and chars + len(scored[j][2]) <= max_chars:
            chars += len(scored[j][2]) + 1
            total += scored[j][3]
            j += 1
        if j > i:
            candidate = (total, chars, i, j)
            if best is None or (candidate[0], -candidate[2]) > (best[0], -best[2]):
                best = candidate
    if not best:
        start, end, text = blocks[0]
        return {'text': text[:max_chars], 'start': start, 'end': end,
                'score': 0, 'reason': 'single_block'}
    total, _chars, i, j = best
    if total == 0 and require_signal:
        return {'text': '', 'start': scored[i][0], 'end': scored[j - 1][1],
                'score': 0, 'reason': 'no_signal_keywords'}
    text = '\n'.join(block[2] for block in scored[i:j])
    return {'text': text.strip(), 'start': scored[i][0], 'end': scored[j - 1][1],
            'score': total, 'reason': ''}


def _blocks(cues, target: int = 420) -> list[tuple[float, float, str]]:
    blocks = []
    start = end = None
    parts = []; chars = 0
    for cue_start, cue_end, text in cues:
        if start is None:
            start = cue_start
        parts.append(text); chars += len(text) + 1; end = cue_end
        if chars >= target:
            blocks.append((start, end, ' '.join(parts)))
            start = end = None; parts = []; chars = 0
    if parts:
        blocks.append((start, end, ' '.join(parts)))
    return blocks


def fetch_subtitles(video_url: str, video_id: str, config: dict, info: dict,
                    cache_root: Path) -> tuple[Path | None, str, str]:
    """Download creator subtitles first, then auto-captions. No Chinese auto-translation."""
    manual = {str(k).lower(): k for k in (info.get('subtitles') or {})}
    auto = {str(k).lower(): k for k in (info.get('automatic_captions') or {})}
    languages = [str(x).lower() for x in config.get('languages') or ['en']]
    chosen = None
    for wanted in languages:
        for keys, kind in ((manual, 'manual'), (auto, 'auto')):
            for key in keys:
                if key == wanted or key.split('-')[0] == wanted.split('-')[0]:
                    if kind == 'auto' and wanted.startswith('zh'):
                        continue
                    chosen = (key, kind); break
            if chosen:
                break
        if chosen:
            break
    if not chosen:
        return None, '', 'no_subtitles'
    lang, kind = chosen
    dest = cache_root / video_id
    dest.mkdir(parents=True, exist_ok=True)
    flag = '--write-subs' if kind == 'manual' else '--write-auto-subs'
    cmd = [str(ytdlp_path()), '--skip-download', flag, '--sub-langs', lang,
           '--sub-format', 'vtt', '--paths', str(dest), '-o', '%(id)s.%(ext)s',
           '--no-warnings', '--no-playlist']
    impersonate = str(config.get('impersonate') or '').strip()
    if impersonate:
        cmd += ['--impersonate', impersonate]
    cmd.append(video_url)
    _run(cmd)
    candidates = sorted(dest.glob(f'{video_id}*.vtt'))
    if not candidates:
        return None, kind, 'subtitle_write_failed'
    source = candidates[0]
    target = dest / 'transcript.vtt'
    if target.exists():
        target.unlink()
    source.replace(target)
    for extra in candidates[1:]:
        extra.unlink(missing_ok=True)
    return target, kind, ''


def video_info(url: str) -> dict:
    return _json([str(ytdlp_path()), '--dump-single-json', '--skip-download',
                  '--no-warnings', '--no-playlist', url])


def collect(config: dict, store=None, cache_root: Path | str = 'data/youtube') -> tuple[list[YouTubeArticle], dict, list[dict]]:
    """Fetch selected videos and return article records ready for the normal pipeline."""
    selected, counters, issues = plan_candidates(config, store)
    articles = []
    cache_root = Path(cache_root)
    for pick in selected:
        source = pick['source']; entry = pick['entry']; video_id = pick['video_id']
        url = str(entry.get('url') or entry.get('webpage_url') or f'https://www.youtube.com/watch?v={video_id}')
        if 'youtube.com/watch' not in url:
            url = f'https://www.youtube.com/watch?v={video_id}'
        try:
            info = video_info(url)
            subtitle_path, kind, reason = fetch_subtitles(url, video_id, config, info, cache_root)
            if subtitle_path is None:
                counters['skipped_reason'][reason] = counters['skipped_reason'].get(reason, 0) + 1
                if store is not None:
                    store.save_youtube_video(_record(source, entry, video_id, url, info, kind, reason))
                continue
            cues = parse_vtt(subtitle_path.read_text(encoding='utf-8', errors='replace'))
            excerpt = select_excerpt(cues, int(config.get('max_transcript_chars', 6000)),
                                     keywords=source.get('signal_keywords') or info.get('_keywords'),
                                     require_signal=bool(config.get('require_signal', True)))
            if not excerpt.get('text'):
                counters['skipped_reason'][excerpt.get('reason') or 'no_excerpt'] = \
                    counters['skipped_reason'].get(excerpt.get('reason') or 'no_excerpt', 0) + 1
                if store is not None:
                    store.save_youtube_video(_record(source, entry, video_id, url, info, kind,
                                                     excerpt.get('reason') or 'no_excerpt'))
                continue
            published = _published(info) or _published(entry)
            title = str(info.get('title') or entry.get('title') or video_id)
            channel = str(info.get('channel') or info.get('uploader') or source.get('name') or '')
            header = (f"[YouTube transcript] {channel} | {title} | {published or 'date unknown'} | "
                      f"subtitles: {kind} | excerpt: {_stamp(excerpt['start'])}-{_stamp(excerpt['end'])}")
            summary = header + '\n\n' + excerpt['text']
            youtube = {'video_id': video_id, 'channel': channel, 'transcript_kind': kind,
                       'excerpt_start': excerpt['start'], 'excerpt_end': excerpt['end'],
                       'transcript_chars': sum(len(c[2]) for c in cues),
                       'transcript_path': str(subtitle_path), 'selection_score': excerpt['score']}
            article = YouTubeArticle(
                article_id=video_id, title=title, url=url, summary=summary, published=published,
                source_name=str(source.get('name') or channel), feed_id='', source_id=str(source.get('source_id') or ''),
                fetched_at=datetime.now(timezone.utc).isoformat(),
                content_source='youtube_transcript', retrieval_status='ok', youtube=youtube)
            articles.append(article)
            counters['fetched'] = counters.get('fetched', 0) + 1
            if store is not None:
                store.save_youtube_video(_record(source, entry, video_id, url, info, kind, 'fetched',
                                                 excerpt=excerpt, article=article))
        except YouTubeUnavailable as exc:
            counters['skipped_reason']['fetch_failed'] = counters['skipped_reason'].get('fetch_failed', 0) + 1
            issues.append({'severity': 'warning', 'code': 'youtube_fetch_failed',
                           'source_id': source.get('source_id'), 'message': f'{video_id}: {str(exc)[:400]}'})
    counters.setdefault('fetched', 0)
    counters['analyzed'] = 0
    return articles, counters, issues


def _record(source, entry, video_id, url, info, kind, status, excerpt=None, article=None) -> dict:
    return {'video_id': video_id, 'source_id': str(source.get('source_id') or ''),
            'channel': str(info.get('channel') or info.get('uploader') or ''),
            'title': str(info.get('title') or entry.get('title') or video_id),
            'url': url, 'published': _published(info) or _published(entry),
            'duration': int(info.get('duration') or entry.get('duration') or 0),
            'transcript_kind': kind, 'status': status, 'reason': status if status not in {'fetched'} else '',
            'transcript_path': str(article.youtube.get('transcript_path') if article else ''),
            'transcript_chars': int(article.youtube.get('transcript_chars') if article else 0),
            'excerpt_start': float(excerpt.get('start') if excerpt else 0),
            'excerpt_end': float(excerpt.get('end') if excerpt else 0),
            'excerpt_chars': len(excerpt.get('text') or '') if excerpt else 0,
            'article_key': hashlib.sha256(url.encode()).hexdigest(), 'fetched_at': datetime.now(timezone.utc).isoformat()}


def explain(url: str, config: dict | None = None, cache_root: Path | str = 'data/youtube') -> dict:
    """Operator-facing check: metadata, subtitle kind, excerpt range and a text preview."""
    config = config or load_config()
    info = video_info(url)
    video_id = str(info.get('id') or '')
    subtitle_path, kind, reason = fetch_subtitles(url, video_id, config, info, Path(cache_root))
    if subtitle_path is None:
        return {'video_id': video_id, 'title': info.get('title', ''), 'reason': reason}
    cues = parse_vtt(subtitle_path.read_text(encoding='utf-8', errors='replace'))
    excerpt = select_excerpt(cues, int(config.get('max_transcript_chars', 6000)),
                             require_signal=bool(config.get('require_signal', True)))
    return {'video_id': video_id, 'title': info.get('title', ''),
            'channel': info.get('channel', ''), 'published': _published(info),
            'duration': info.get('duration'), 'transcript_kind': kind,
            'cues': len(cues), 'transcript_chars': sum(len(c[2]) for c in cues),
            'excerpt_start': excerpt['start'], 'excerpt_end': excerpt['end'],
            'excerpt_score': excerpt['score'], 'reason': excerpt['reason'],
            'excerpt': excerpt['text'][:600]}
