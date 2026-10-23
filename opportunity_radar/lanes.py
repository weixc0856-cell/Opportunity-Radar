"""Editorial lanes: the same article means different things in different channels.

Lane A asks "what changed and why does it matter", lane B asks "who is blocked and
would pay", lane C asks "what is worth tracking technically". Ranking all three on one
scale forced community questions to compete with company news on payment evidence, so
neither could be scored on its own terms.
"""
import re

LANES=('A','B','C')
LANE_LABEL={'A':'商业、科技与经济情报','B':'客户痛点与商业机会','C':'技术观察与工程信号'}
LANE_PROMISE={
 'A':'今天发生了什么重要变化，为什么值得关注',
 'B':'谁遇到了什么问题，有没有人愿意为此付费',
 'C':'哪些技术变化值得跟踪，但还不足以得出商业结论',
}
DEFAULT_LANE_BY_SOURCE_TYPE={
 'user_forum':'B','project_launch':'B','community_aggregator':'B',
 'research_feed':'C','open_source_project':'C',
 'official_blog':'A','vendor_blog':'A','news_media':'A','independent_expert':'A',
 'investor_relations':'A','government':'A','industry_association':'A','research_organization':'A',
}
COMMUNITY_TYPES={'user_forum','project_launch','community_aggregator'}
TECHNICAL_TYPES={'research_feed','open_source_project'}

def _src(source,name,default=''):
    if source is None: return default
    if isinstance(source,dict): return source.get(name,default) or default
    return getattr(source,name,default) or default

def lanes_of(source):
    """Declared lanes for a source, in canonical order. Empty when undeclared."""
    raw=str(_src(source,'editorial_lanes') or '').upper()
    found={t for t in re.split(r'[\s,;|/]+',raw) if t}
    return tuple(l for l in LANES if l in found)

def content_lane(analysis,classification):
    """Which lane the content belongs to, ignoring the source's declarations."""
    cls=classification or {}; a=analysis or {}
    kind=str(cls.get('article_type') or 'general').lower()
    signal=str(cls.get('signal_type') or '').lower()
    if kind=='hiring': return 'B'
    if signal=='payment_demand' or kind=='user_pain': return 'B'
    if kind=='funding': return 'A'
    if kind=='tech': return 'C'
    if kind=='product': return 'C' if cls.get('source_quality') in {'project_record'} else 'A'
    if str(a.get('category') or '').lower()=='market_change': return 'A'
    return 'A'

def derive_lane(article=None,analysis=None,source=None,classification=None):
    """Route an article deterministically.

    A source declaration narrows the choice; within it the content decides. An
    undeclared community source that produced only a general post still defaults to
    lane B, because that is what its users contribute.
    """
    cls=classification or {}
    content=content_lane(analysis,cls)
    st=str(_src(source,'source_type') or '').lower()
    # A release note from a research or open-source source is technical tracking, not
    # company news, even though the classifier sees the word "release" in both.
    if content=='A' and str(cls.get('article_type') or '').lower()=='product' and st in TECHNICAL_TYPES:
        content='C'
    declared=lanes_of(source)
    if declared:
        if content in declared: return content
        return next((l for l in LANES if l in declared),content)
    if content=='A' and str(cls.get('article_type') or 'general').lower()=='general':
        st=str(_src(source,'source_type') or '').lower()
        if st in COMMUNITY_TYPES: return 'B'
        return DEFAULT_LANE_BY_SOURCE_TYPE.get(st,'A')
    return content

def item_lane(item):
    """Lane of an already-scored record, including ones archived before lanes existed."""
    lane=(item or {}).get('lane')
    if lane in LANES: return lane
    return derive_lane({},(item or {}).get('analysis',{}),None,(item or {}).get('classification',{}))
