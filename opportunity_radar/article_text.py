"""N0: document normalisation with reproducible character positions.

N0 takes one article - the title plus the body this system actually holds - and produces one
searchable text with paragraph and sentence records whose offsets tile that text. Every later
node reads this object and nothing else, so nobody re-normalises the text and ends up with
different offsets.

Offsets are Unicode code points (Python string indices) and half-open: `text[start:end]`
returns exactly the record's text. The canonical text is the same text `schema._normalize`
produces for HTML input - tags become a space, entities are decoded, curly quotes are folded,
whitespace is collapsed, the result is lower-cased - because that is the text the evidence
locator already stores and searches. N0 does not rewrite numbers: `0.2 percent` stays
`0.2 percent` and `$92.8bn` stays `$92.8bn`.

The searchable text is the title followed by the body. The title is its own paragraph
(`paragraphs[0].field == 'title'`) and `body_start` says where the body begins. A key figure
often appears only in the title, so leaving it out would silently lose it.

N1 scans this text. N0 does not decide what any number means.
"""
from __future__ import annotations

import hashlib
import re
from html import unescape
from pathlib import Path

VERSION = 'n0-v1'
# The source hash is recorded with every run so a rule change cannot reuse a
# result produced by different rules under the same node version.
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]
OFFSET_UNIT = 'unicode_codepoint'
OFFSET_CONVENTION = 'half_open'

# The same tag rule schema._normalize uses; a construct that is not matched here stays text.
_TAG = re.compile(r'<[^>]+>')
# Block boundaries are where a paragraph can start or end. They are found on the raw HTML
# before tags are removed, because after removal a <br> is indistinguishable from a <b>.
_BLOCK = re.compile(
    r'<\s*/?\s*(?:br|p|div|li|ul|ol|dl|dt|dd|h[1-6]|tr|td|th|thead|tbody|table|'
    r'blockquote|section|article|header|footer|figure|figcaption)\b[^>]*>', re.I)
# The token html.unescape recognises. Using its own pattern keeps decoding identical.
_ENTITY = re.compile(r'&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)')
_FOLD = {'“': '"', '”': '"', '‘': "'", '’': "'", '\xa0': ' '}
# A period ends a sentence only when the next character is not part of the same number or
# word. These are the abbreviations that otherwise split a sentence in the middle.
_SENTENCE_END = re.compile(r'[.!?。！？]+')
_ABBREVIATIONS = {
    'u.s', 'u.k', 'u.n', 'e.g', 'i.e', 'vs', 'etc', 'inc', 'ltd', 'co', 'corp', 'plc', 'llc',
    'mr', 'mrs', 'ms', 'dr', 'prof', 'no', 'nos', 'st', 'jr', 'sr', 'approx', 'dept', 'est',
    'fig', 'figs', 'al', 'ed', 'vol', 'bros', 'gov', 'sen', 'rep',
}
_BLANK_LINE = re.compile(r'\n\s*\n')


def _value(article, name, default=''):
    if article is None:
        return default
    if isinstance(article, dict):
        value = article.get(name, default)
    else:
        value = getattr(article, name, default)
    return default if value is None else value


def _input(article):
    """(title, body, content_format, metadata) from an article object or a contract dict."""
    title = str(_value(article, 'title', '') or '')
    content = _value(article, 'content', None)
    if content is None:
        # The existing RSS model calls the body `summary`; the contract calls it `content`.
        content = _value(article, 'summary', '')
    content_format = str(_value(article, 'content_format', '') or '').strip().lower()
    if not content_format:
        content_format = 'html'
    metadata = {
        'article_id': str(_value(article, 'article_id', '') or ''),
        'source_id': str(_value(article, 'source_id', '') or _value(article, 'feed_id', '') or ''),
        'source_url': str(_value(article, 'source_url', '') or _value(article, 'url', '') or ''),
        'language': str(_value(article, 'language', '') or ''),
        'content_truncated': bool(_value(article, 'content_truncated', False)),
    }
    return title, str(content or ''), content_format, metadata


def _drop_tags(raw):
    """(chars, spans) with each tag replaced by one space; spans point into `raw`."""
    chars, spans, last = [], [], 0
    for match in _TAG.finditer(raw):
        for index in range(last, match.start()):
            chars.append(raw[index])
            spans.append((index, index + 1))
        chars.append(' ')
        spans.append((match.start(), match.end()))
        last = match.end()
    for index in range(last, len(raw)):
        chars.append(raw[index])
        spans.append((index, index + 1))
    return chars, spans


def _decode_entities(chars, spans):
    """Decode the entities html.unescape would decode, keeping the raw span they came from."""
    text = ''.join(chars)
    out_chars, out_spans, last = [], [], 0
    for match in _ENTITY.finditer(text):
        decoded = unescape(match.group(0))
        if decoded == match.group(0):
            continue
        for index in range(last, match.start()):
            out_chars.append(text[index])
            out_spans.append(spans[index])
        raw_start, raw_end = spans[match.start()][0], spans[match.end() - 1][1]
        for char in decoded:
            out_chars.append(char)
            out_spans.append((raw_start, raw_end))
        last = match.end()
    for index in range(last, len(text)):
        out_chars.append(text[index])
        out_spans.append(spans[index])
    return out_chars, out_spans


def _canonicalise(chars, spans):
    """Fold quotes, collapse whitespace, lower case; length changes are mapped, not lost."""
    out, out_spans, pending = [], [], None
    for char, span in zip(chars, spans):
        char = _FOLD.get(char, char)
        if char.isspace():
            if pending is None and out:
                pending = (' ', span)
            continue
        if pending is not None:
            out.append(pending[0])
            out_spans.append(pending[1])
            pending = None
        for lowered in char.lower():
            out.append(lowered)
            out_spans.append(span)
    return ''.join(out), out_spans


def normalise(raw, strip_tags=True):
    """(text, spans): the canonical text and, per character, its span in `raw`.

    `strip_tags=False` is for inputs the caller has already declared plain text, so a
    literal '<' in prose is not mistaken for a tag.
    """
    raw = str(raw or '')
    if strip_tags:
        chars, spans = _drop_tags(raw)
    else:
        chars, spans = list(raw), [(index, index + 1) for index in range(len(raw))]
    chars, spans = _decode_entities(chars, spans)
    return _canonicalise(chars, spans)


def _paragraph_spans_html(raw):
    """Raw spans of the paragraphs in `raw`, split at block tags. Empty ones are dropped."""
    spans, last = [], 0
    for match in _BLOCK.finditer(raw):
        if raw[last:match.start()].strip():
            spans.append((last, match.start()))
        last = match.end()
    if raw[last:].strip():
        spans.append((last, len(raw)))
    return spans


def _paragraph_spans_text(raw):
    """Raw spans of the paragraphs in plain text, split at blank lines."""
    spans, last = [], 0
    for match in _BLANK_LINE.finditer(raw):
        if raw[last:match.start()].strip():
            spans.append((last, match.start()))
        last = match.end()
    if raw[last:].strip():
        spans.append((last, len(raw)))
    if not spans and raw.strip():
        spans.append((0, len(raw)))
    return spans


def _is_abbreviation(text, dot):
    token = text[max(0, dot - 10):dot]
    match = re.search(r'([a-z0-9.]+)$', token)
    if not match:
        return False
    word = match.group(1)
    return word in _ABBREVIATIONS or bool(re.fullmatch(r'(?:[a-z]\.)+[a-z]', word))


def sentence_spans(text):
    """(start, end) of each sentence. A deterministic boundary rule, not a parser.

    A period inside a number ('92.8') or an abbreviation ('u.s.') does not end a sentence;
    everything else after '.', '!', '?' or the Chinese equivalents does. Offsets tile the
    text: every non-space character belongs to exactly one sentence.
    """
    spans, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        if end < len(text) and not (text[end].isspace() or text[end] in ')]"\''):
            continue
        if match.group(0)[0] == '.' and _is_abbreviation(text, match.start()):
            continue
        if end <= start:
            continue
        spans.append((start, end))
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


class Field:
    """One input field (title or body) with its text, raw spans and structure."""

    def __init__(self, name, text, spans, global_start, raw_start, raw_end):
        self.name = name
        self.text = text
        self.spans = spans
        self.global_start = global_start
        self.raw_start = raw_start
        self.raw_end = raw_end

    def raw_span(self, start, end):
        """The span in the raw input that the canonical text[start:end] came from."""
        if not self.spans:
            return self.raw_start, self.raw_start
        start = max(0, min(start, len(self.spans) - 1))
        end = max(start + 1, min(end, len(self.spans)))
        return self.spans[start][0], self.spans[end - 1][1]

    def to_dict(self):
        return {'text': self.text, 'global_start': self.global_start,
                'raw_start': self.raw_start, 'raw_end': self.raw_end,
                'characters': len(self.text)}


class ArticleText:
    """The normalised article: N0's output and the input of every later node."""

    def __init__(self, fields, paragraphs, sentences, content_hash, document_id,
                 title, metadata, content_characters, truncated):
        self.fields = fields
        self.paragraphs = paragraphs
        self.sentences = sentences
        self.content_hash = content_hash
        self.source_hash = content_hash          # the Batch 7 name, kept as an alias
        self.document_id = document_id
        self.title = title
        self.metadata = metadata
        self.content_characters = content_characters
        self.content_truncated = truncated
        self.text = ' '.join(field.text for field in fields.values() if field.text)
        self.text_hash = hashlib.sha256(self.text.encode('utf-8')).hexdigest()
        self.body_start = fields['body'].global_start if 'body' in fields else None

    def field(self, name):
        field = self.fields.get(name)
        if field is None:
            raise KeyError(f'no field named {name!r}')
        return field

    def paragraph_of(self, field_name, start):
        """Index into `paragraphs` of the paragraph containing `start` in `field_name`."""
        for paragraph in self.paragraphs:
            if (paragraph['field'] == field_name
                    and paragraph['field_start'] <= start < paragraph['field_end']):
                return paragraph['index']
        return None

    def sentence_of(self, field_name, start):
        """Index into `sentences` of the sentence containing `start` in `field_name`."""
        for sentence in self.sentences:
            if (sentence['field'] == field_name
                    and sentence['field_start'] <= start < sentence['field_end']):
                return sentence['index']
        return None

    def raw_span(self, field_name, start, end):
        return self.field(field_name).raw_span(start, end)

    def to_dict(self):
        counts = {name: len(field.text) for name, field in self.fields.items()}
        return {
            'document_id': self.document_id,
            'article_id': self.metadata['article_id'],
            'source_id': self.metadata['source_id'],
            'normalization_version': VERSION,
            'ruleset': RULESET,
            'content_hash': self.content_hash,
            'source_hash': self.content_hash,
            'text_hash': self.text_hash,
            'title': self.title,
            'text': self.text,
            'body_start': self.body_start,
            'language': self.metadata['language'],
            'source_url': self.metadata['source_url'],
            'content_format': self.metadata['content_format'],
            'offset_unit': OFFSET_UNIT,
            'offset_convention': OFFSET_CONVENTION,
            'paragraphs': self.paragraphs,
            'sentences': self.sentences,
            'content_truncated': self.content_truncated,
            'stats': {'characters': len(self.text), 'field_characters': counts,
                      'content_characters': self.content_characters,
                      'paragraphs': len(self.paragraphs),
                      'sentences': len(self.sentences)},
        }


def build(article):
    """Normalise one article. Raises ValueError when there is no text to normalise."""
    title_raw, body_raw, content_format, metadata = _input(article)
    if not title_raw.strip() and not body_raw.strip():
        raise ValueError('article has no title or content text')
    metadata['content_format'] = content_format
    content_hash = hashlib.sha256(
        (title_raw + '\x00' + body_raw).encode('utf-8')).hexdigest()
    document_id = hashlib.sha256(
        (VERSION + '\x00' + content_hash).encode('utf-8')).hexdigest()

    html = content_format != 'text'
    raw_fields = (
        ('title', [(0, len(title_raw))] if title_raw.strip() else [], title_raw, False),
        ('body', _paragraph_spans_html(body_raw) if html else _paragraph_spans_text(body_raw),
         body_raw, html),
    )
    fields, paragraphs, sentences = {}, [], []
    global_cursor = 0
    for name, spans_of_field, raw, strip_tags in raw_fields:
        chars, spans, paragraph_texts = [], [], []
        for raw_start, raw_end in spans_of_field:
            text, local_spans = normalise(raw[raw_start:raw_end], strip_tags=strip_tags)
            if not text:
                continue
            if chars:
                chars.append(' ')
                spans.append((raw_start, raw_start))
            start_in_field = len(chars)
            chars.extend(text)
            spans.extend((a + raw_start, b + raw_start) for a, b in local_spans)
            paragraph_texts.append((start_in_field, len(chars), text, raw_start, raw_end))
        field_text = ''.join(chars)
        if not field_text:
            continue
        fields[name] = Field(name, field_text, spans, global_cursor, 0, len(raw))
        for start, end, text, raw_start, raw_end in paragraph_texts:
            within_field = len([p for p in paragraphs if p['field'] == name])
            paragraphs.append({
                'index': len(paragraphs), 'paragraph_id': f'p{len(paragraphs) + 1:04d}',
                'field': name, 'paragraph': within_field,
                'start': global_cursor + start, 'end': global_cursor + end,
                'field_start': start, 'field_end': end,
                'global_start': global_cursor + start, 'global_end': global_cursor + end,
                'raw_start': raw_start, 'raw_end': raw_end, 'text': text,
            })
            for sentence_start, sentence_end in sentence_spans(text):
                sentences.append({
                    'index': len(sentences), 'sentence_id': f's{len(sentences) + 1:04d}',
                    'segment': len(paragraphs) - 1,
                    'paragraph': len(paragraphs) - 1,
                    'paragraph_id': paragraphs[-1]['paragraph_id'],
                    'field': name,
                    'start': global_cursor + start + sentence_start,
                    'end': global_cursor + start + sentence_end,
                    'field_start': start + sentence_start, 'field_end': start + sentence_end,
                    'global_start': global_cursor + start + sentence_start,
                    'global_end': global_cursor + start + sentence_end,
                    'text': text[sentence_start:sentence_end],
                })
        global_cursor += len(field_text) + 1
    if not fields:
        raise ValueError('article has no title or content text')
    return ArticleText(fields, paragraphs, sentences, content_hash, document_id,
                       title_raw, metadata, len(body_raw), metadata['content_truncated'])
