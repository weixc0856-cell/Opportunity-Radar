"""Explicit SEC tag mapping for the ten companies in the condition-1 sample matrix.

docs/archive/SEC_SAMPLE_MATRIX_2026-11-01.md is the authority for these rows. A metric with no
verified tag is recorded as unsupported rather than guessed; sparse or dimensional cases are
marked requires_filing_parse.
"""

SUPPORTED = 'supported'
UNSUPPORTED = 'unsupported'
REQUIRES_FILING_PARSE = 'requires_filing_parse'

REVENUE = 'revenue'
CAPEX = 'capex'

US_GAAP = 'us-gaap'
IFRS = 'ifrs-full'


def _tag(taxonomy, tag, status=SUPPORTED):
    return {'taxonomy': taxonomy, 'tag': tag, 'status': status}


COMPANIES = {
    '0000320193': {'name': 'Apple Inc.', 'ticker': 'AAPL', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'RevenueFromContractWithCustomerExcludingAssessedTax')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0000789019': {'name': 'Microsoft Corp.', 'ticker': 'MSFT', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'RevenueFromContractWithCustomerExcludingAssessedTax')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0001045810': {'name': 'NVIDIA Corp.', 'ticker': 'NVDA', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquireProductiveAssets')]}},
    '0000019617': {'name': 'JPMorgan Chase & Co.', 'ticker': 'JPM', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'RevenuesNetOfInterestExpense')],
        CAPEX: [_tag(US_GAAP, '', UNSUPPORTED)]}},
    '0002115436': {'name': 'Exxon Mobil Corp.', 'ticker': 'XOM', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues', REQUIRES_FILING_PARSE)],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment', REQUIRES_FILING_PARSE)]}},
    '0001318605': {'name': 'Tesla, Inc.', 'ticker': 'TSLA', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues'),
                  _tag(US_GAAP, 'RevenueFromContractWithCustomerExcludingAssessedTax', 'alternate')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0000018230': {'name': 'Caterpillar Inc.', 'ticker': 'CAT', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0000021344': {'name': 'The Coca-Cola Company', 'ticker': 'KO', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0000731766': {'name': 'UnitedHealth Group Inc.', 'ticker': 'UNH', 'metrics': {
        REVENUE: [_tag(US_GAAP, 'Revenues')],
        CAPEX: [_tag(US_GAAP, 'PaymentsToAcquirePropertyPlantAndEquipment')]}},
    '0001046179': {'name': 'Taiwan Semiconductor Manufacturing Co.', 'ticker': 'TSM', 'metrics': {
        REVENUE: [_tag(IFRS, 'Revenue')],
        CAPEX: [_tag(IFRS, 'PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities')]}},
}


def companies():
    return sorted(COMPANIES)


def requested_tags():
    """(cik, metric_id, taxonomy, tag, status) for every fetchable tag, sorted for determinism."""
    out = []
    for cik in companies():
        for metric, refs in COMPANIES[cik]['metrics'].items():
            for ref in refs:
                if ref['status'] == UNSUPPORTED:
                    continue
                out.append((cik, metric, ref['taxonomy'], ref['tag'], ref['status']))
    return sorted(out)


def unsupported():
    return [(cik, metric) for cik in companies()
            for metric, refs in COMPANIES[cik]['metrics'].items()
            if all(r['status'] == UNSUPPORTED for r in refs)]
