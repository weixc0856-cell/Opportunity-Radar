import re

# Deterministic triage rules. The model's own "category" is one input, not the verdict.
HIRING=re.compile(r'\b(hiring|job (?:opening|posting)|recruiting|join our team|looking for (?:an?|engineers?|developers?))\b|招聘|诚聘|求职|岗位',re.I)
FUNDING=re.compile(r'\b(raises?|raised|funding|series [a-e]\b|valuation|acquired|acquisition|ipo|merger|investors?)\b|融资|收购|估值',re.I)
PAIN=re.compile(r'\b(struggle|pain|frustrat|problem|annoying|too slow|takes? (hours|days)|manual|tedious|expensive|how do (you|i)|why (does|do)|wish (there|it))\b|痛点|麻烦|耗时|效率|抱怨',re.I)
TECH=re.compile(r'\b(open[- ]source|github|librar(y|ies)|framework(s)?|compiler(s)?|benchmark(s)?|driver(s)?|kernel(s)?|sdk(s)?|protocol(s)?|algorithm(s)?|filters?)\b|开源|框架|驱动|算法',re.I)
PRODUCT=re.compile(r'\b(launch(es|ed|ing)?|releas(e|es|ed|ing)|introduc(e|es|ed|ing)|announc(e|es|ed|ing)|now available|unveil(s|ed)?|ship(s|ped)?)\b|发布|推出|上线',re.I)
# Broad commercial terms are only indirect signals. Direct payment evidence uses
# narrower phrases so a generic 'pricing page' or 'already use' is not mislabeled as a sale.
PAYMENT=re.compile(r'\b(paid|paying|purchase|buy|budget|pricing|subscription|revenue|profit|invoice|procurement)\b|付费|采购|预算|收入|营收|发票',re.I)
EXPLICIT_BUDGET=re.compile(r'\b(budget available|budget approved|budget allocated|have a budget|has a budget|budget of \$?\d|budget:? \$?\d|allocated budget|approved budget)\b|明确预算|预算已批|预算已落实|有预算|预算为[0-9]',re.I)
WILLING=re.compile(r'\b(willing to pay|would pay|happy to pay|ready to pay|willing to purchase|will pay for|i would pay|we would pay|pay for this|pay for a tool|pay for a solution)\b|愿意付费|愿意购买|愿意支付',re.I)
EXISTING_PAID=re.compile(r'\b(already paid|already pay|currently paying|currently pay|paid for|paid \$\d|paying \$\d|purchased|purchase order|paid subscription|customers? pay for|already a paying customer|renewed (the )?subscription)\b|已付费|已经付费|已采购|付费购买|已支付|采购订单',re.I)
DEPLOY=re.compile(r'\b(error|fail(s|ed|ing)?|install(ation|ing)?|deploy(ment|ing)?|integrat(e|ion|ing)|migrat(e|ion)|compatib(le|ility)|crash(es|ed)?|doesn.t work|not working|performance)\b|报错|部署|集成|兼容|失败|崩溃|性能',re.I)
GAP=re.compile(r'\b(missing|feature request|support for|wish (there|it)|would be nice|not supported|no support|add support|need a way)\b|不支持|缺失|希望|建议增加',re.I)
SERVICE=re.compile(r'\b(consult(ing|ant)?|custom development|automation|freelanc|contract work|outsourc)\b|咨询|定制开发|自动化|外包',re.I)

# A seller publishing a price is not a buyer agreeing to pay. These signals are recorded
# separately so the briefing can keep an early commercial lead without ever presenting
# vendor marketing as verified demand.
SELLER_SERVICE=re.compile(r'\b(paid support|commercial support|consulting services|book a demo|contact sales|enterprise (?:plan|tier|edition)|paid (?:plan|tier)|premium (?:plan|tier)|request a quote)\b|商业支持|付费支持|企业版|咨询服务|预约演示|报价',re.I)
SELLER_PRICING=re.compile(r'\b(pricing (?:page|plan|tier)|subscription (?:plan|price|tier)|list price|licen[cs]e fee|per seat)\b|定价|价格页|订阅套餐',re.I)
ADOPTION=re.compile(r'\b(in production|production use|running in production|deployed at|deployed to|rolling out|adopted by|case study|customers? (?:use|rely on|deployed))\b|生产环境|已部署|客户案例|正式上线',re.I)
PAIN_REPEAT=re.compile(r'\b(again|still (?:fails|broken|happening)|recurring|every (?:time|week|month|run)|same (?:issue|problem|error)|others? (?:also|report|have))\b|再次|仍然|反复|每次都|其他人也',re.I)
PRODUCT_HINT=re.compile(r'\b(tool|app|saas|plugin|extension|platform)\b|工具|插件|平台',re.I)
ENTERPRISE=re.compile(r'\b(enterprise|company|companies|organization|procurement|on-prem|compliance|IT department)\b|企业|公司|采购|合规',re.I)
ENGINEER=re.compile(r'\b(engineer(s|ing)?|simulation|CFD|CAE|FEA|mesh(ing)?|solver|OpenFOAM|Ansys|SolidWorks|CAD|post-?process(ing)?|turbulence|geometry)\b|仿真|网格|求解器|工程|后处理|湍流',re.I)
DEV=re.compile(r'\b(developer|indie|side project|founder|freelancer)\b|开发者|独立开发',re.I)
SMB=re.compile(r'\b(small business|shop|restaurant|bakery|retail|clinic)\b|小企业|餐厅|零售|门店',re.I)
VENDOR=re.compile(r'\b(release[ds]?|announc(e|es|ed|ing)|introduc(e|es|ed|ing)|launch(es|ed|ing)?|version \d|v\d+\.\d+)\b|发布|推出|版本',re.I)
FORUM_HOSTS=('discourse.','community.','forum.')

def _source_quality(article,kind,text,source=None):
    """Declared provenance from the source registry wins; URL heuristics are the fallback.
    Source identity is separate from how much the content proves: a forum post is first-party
    user expression even when the post itself is a feature request or a technical question."""
    declared=str((source.get('provenance_class','') if isinstance(source,dict) else getattr(source,'provenance_class','')) or '').strip().lower()
    if declared: return declared
    url=(_field(article,'url') or '').lower(); name=(_field(article,'source_name') or '').lower()
    if '.invalid' in url or name in {'sample only','offline sample','离线示例'}: return 'unknown'
    if any(h in url for h in FORUM_HOSTS) or 'forum' in name or 'community' in name: return 'first_party'
    if 'news.ycombinator.com' in url or 'hnrss.org' in url: return 'first_party'
    if 'github.com' in url and '/releases' in url: return 'project_record'
    if kind=='user_pain': return 'first_party'
    if VENDOR.search(text): return 'vendor_marketing'
    return 'secondhand_report'

TYPES=('hiring','funding','user_pain','tech','product','general')
BUSINESS_TYPES={'user_pain','product','funding'}
STRENGTH={'none':0,'weak':1,'moderate':2,'strong':3}

def _field(article,name,default=''):
    return article.get(name,default) if isinstance(article,dict) else getattr(article,name,default)

def text_of(article):
    return f"{_field(article,'title')} {_field(article,'summary')}".strip()

def content_source(article):
    summary=(_field(article,'summary') or '').strip()
    return 'rss_summary' if summary else 'title_only'

def classify(article,analysis,source=None):
    """Return how the article should be triaged, independent of how promising it looks."""
    t=text_of(article)
    if HIRING.search(t): kind='hiring'
    elif FUNDING.search(t): kind='funding'
    elif str(analysis.get('category','')).lower()=='customer_pain' or PAIN.search(t): kind='user_pain'
    elif TECH.search(t): kind='tech'
    elif PRODUCT.search(t): kind='product'
    else: kind='general'
    # Payment evidence must come from the article text, never from the model's own commentary.
    payment_hits=len(PAYMENT.findall(t))
    category=str(analysis.get('category','unknown')).lower()
    direct_budget=bool(EXPLICIT_BUDGET.search(t))
    willingness=bool(WILLING.search(t))
    existing_paid=bool(EXISTING_PAID.search(t))
    if direct_budget or willingness or existing_paid: strength='strong'
    elif payment_hits: strength='moderate'
    elif category in {'customer_pain','small_business','service_opportunity','market_change'}: strength='weak'
    else: strength='none'
    summary=(_field(article,'summary') or '').strip()
    signal=('payment_demand' if direct_budget or willingness else
            'user_pain' if kind=='user_pain' else
            'deployment_blocker' if DEPLOY.search(t) else
            'product_gap' if GAP.search(t) else 'tech_trend')
    buyer=('engineering_team' if ENGINEER.search(t) else
           'enterprise_it' if ENTERPRISE.search(t) else
           'individual_dev' if DEV.search(t) else
           'smb' if SMB.search(t) else 'unknown')
    pay=('explicit_budget' if direct_budget else
         'stated_willingness' if willingness else
         'existing_purchase' if existing_paid else
         'indirect' if payment_hits else 'none')
    # Direct buyer evidence is only what the article attributes to a buyer. 'indirect' is
    # a keyword hit, so it stays out of the buyer field and out of the business score.
    buyer_pay=pay if pay in {'explicit_budget','stated_willingness','existing_purchase'} else 'none'
    seller=('commercial_service' if SELLER_SERVICE.search(t) else
            'pricing_published' if SELLER_PRICING.search(t) else 'none')
    adoption='production_use' if ADOPTION.search(t) else 'none'
    pain=('repeated' if PAIN_REPEAT.search(t) else
          'single_report' if kind=='user_pain' or DEPLOY.search(t) or GAP.search(t) else 'none')
    delivery=('service' if SERVICE.search(t) else
              'product' if signal=='product_gap' or (PRODUCT_HINT.search(t) and kind=='product') else
              'custom_tool' if kind in {'user_pain','tech'} else 'not_fit')
    source_quality=_source_quality(article,kind,t,source)
    return {'article_type':kind,'payment_hits':payment_hits,'signal_strength':strength,
            'business_relevant':kind in BUSINESS_TYPES or category in {'customer_pain','small_business','service_opportunity'},
            'content_source':content_source(article),'content_length':len(summary),
            'content_status':'ok' if summary else 'empty',
            'signal_type':signal,'buyer_type':buyer,'payment_evidence':pay,
            'buyer_payment_evidence':buyer_pay,'seller_monetization_signal':seller,
            'adoption_signal':adoption,'pain_evidence':pain,
            'delivery_fit':delivery,'source_quality':source_quality}
