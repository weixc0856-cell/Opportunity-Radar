"""Deterministic evidence state.

Evidence is what the supplied text can support, not what a model asserts. Keeping the
state in one closed enum means the report can never print an unlocated quotation as a
verified fact, and the scorer can gate promotion on a stated evidence basis instead of
on a number the model chose.

Two rules shape this module:

1. A heuristic may *estimate* completeness, but only a reviewed source declaration may
   grant it. Length is not proof: 400 characters can be a complete short post or the
   first half of a long article whose feed never emitted a truncation marker.
2. Counting sources is not verification. Two outlets running the same wire story, or a
   vendor release plus a blog repeating it, are coverage, not confirmation.
"""
import re
from html import unescape

# How much of the article the source actually delivered, as far as we may rely on it.
CONTENT_BASIS=('full_text','excerpt','title_only')
# Audit vocabulary for the registry column of the same name. Only 'full_text' — a
# decision made during source review — can reach E2.
CONTENT_ACCESS=('auto','full_text','excerpt','title_only')

EVIDENCE_STATES=('none','title_only','unlocated_quotes','rss_excerpt_only',
                 'full_text_verified','primary_source_located','multi_source_coverage')
STATE_LABEL={
 'none':'E0 · 无引文',
 'title_only':'E0 · 仅标题',
 'unlocated_quotes':'E0 · 引文无法定位',
 'rss_excerpt_only':'E1 · 摘要引文已定位',
 'full_text_verified':'E2 · 正文引文已定位',
 'primary_source_located':'E2 · 一手来源原文已核对',
 'multi_source_coverage':'E2 · 多来源覆盖（未做主张级核对）',
}
# What each E2 state actually establishes. Printed in the appendix so a reader cannot
# mistake "the actor published this" for "this is true".
STATE_MEANING={
 'full_text_verified':'引文可在收到的正文中定位；不代表正文里的每个事实都已被独立证实。',
 'primary_source_located':'引文可在该一手来源自己的发布中定位；这只确认对方这样说过，不代表该说法成立。',
 'multi_source_coverage':'同一事件有多个来源的已分析条目；尚未核对这些来源是否独立、是否重复了同一稿源。',
}
# Legacy vocabulary, kept so analyses archived before this upgrade keep rendering.
LEGACY_LEVEL={'none':'none','title_only':'title','unlocated_quotes':'untraceable',
              'rss_excerpt_only':'summary','full_text_verified':'full_text',
              'primary_source_located':'full_text','multi_source_coverage':'full_text'}
LEGACY_TO_STATE={'none':'none','title':'title_only','untraceable':'unlocated_quotes',
                 'summary':'rss_excerpt_only','full_text':'full_text_verified'}
# States that existed briefly under their old names, before claim-level verification.
STATE_ALIASES={'cross_source_confirmed':'multi_source_coverage','primary_source_verified':'primary_source_located'}
EVIDENCE_RANK={'none':'E0','title_only':'E0','unlocated_quotes':'E0',
               'rss_excerpt_only':'E1','full_text_verified':'E2',
               'primary_source_located':'E2','multi_source_coverage':'E2'}
# A vendor's own announcement is first-party text but not independent verification.
PRIMARY_PROVENANCE={'first_party','project_record'}

FULL_TEXT_MIN_CHARS=400
TRUNCATED_TAIL_CHARS=160
TRUNCATED=re.compile(r'(\[\s*…\s*\]|\[…\]|\.\.\.|…|read more|continue reading|read the full|'
                     r'全文|阅读原文|查看全文)\s*$',re.I)
TAG=re.compile(r'<[^>]+>')

def _src(source,name,default=''):
    if source is None: return default
    if isinstance(source,dict): return source.get(name,default) or default
    return getattr(source,name,default) or default

def plain_text(value):
    return re.sub(r'\s+',' ',unescape(TAG.sub(' ',str(value or '')))).strip()

def looks_truncated(text,tail=TRUNCATED_TAIL_CHARS):
    """A feed that ends in 'read more' or an ellipsis handed us a teaser, not a body."""
    return bool(TRUNCATED.search(plain_text(text)[-tail:]))

def declared_access(source):
    value=str(_src(source,'content_access_level','auto') or 'auto').strip().lower()
    return value if value in CONTENT_ACCESS else 'auto'

def body_text(article):
    return plain_text(article.get('summary') if isinstance(article,dict) else getattr(article,'summary',''))

def content_basis_estimate(article,source=None,min_chars=FULL_TEXT_MIN_CHARS):
    """The program's guess at completeness. Review aid only; never grants E2."""
    body=body_text(article)
    if not body: return 'title_only'
    access=declared_access(source)
    if access in {'full_text','title_only'}: return access
    if len(body)>=min_chars and not looks_truncated(body): return 'full_text'
    return 'excerpt'

def content_basis(article,source=None,min_chars=FULL_TEXT_MIN_CHARS):
    """What we may rely on, as opposed to what the text looks like.

    Only a source reviewed as full-text qualifies. 'auto' and 'excerpt' both stay at
    excerpt however long the text is: an unreviewed feed cannot prove it sent the body.
    """
    body=body_text(article)
    if not body: return 'title_only'
    access=declared_access(source)
    if access=='full_text': return 'full_text'
    if access=='title_only': return 'title_only'
    return 'excerpt'

def state_for(basis,fields,multi_source=False,provenance=''):
    """fields: one locator per quote, 'title' | 'summary' | 'unlocated'."""
    if not fields: return 'none'
    if any(f=='unlocated' for f in fields): return 'unlocated_quotes'
    if basis=='title_only' or all(f=='title' for f in fields): return 'title_only'
    if basis!='full_text': return 'rss_excerpt_only'
    if str(provenance or '').strip().lower() in PRIMARY_PROVENANCE: return 'primary_source_located'
    if multi_source: return 'multi_source_coverage'
    return 'full_text_verified'

def state_of(item):
    """Read the state from a new record or reconstruct it from an archived one."""
    value=str((item or {}).get('evidence_state') or '')
    value=STATE_ALIASES.get(value,value)
    if value in EVIDENCE_STATES: return value
    return LEGACY_TO_STATE.get(str((item or {}).get('evidence_level') or 'none').lower(),'none')

def rank_of(state):
    return EVIDENCE_RANK.get(state,'E0')

RANK_ORDER={'E0':0,'E1':1,'E2':2}

def rank_at_least(rank,minimum):
    """True when a rank meets the lane's promotion gate. Unknown gates fail closed."""
    return RANK_ORDER.get(str(rank).upper(),0)>=RANK_ORDER.get(str(minimum).upper(),2)
