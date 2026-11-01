"""N0: the article, normalised once, with offsets every later node reuses.

The claim pipeline (`docs/CLAIM_PIPELINE.md`) starts here. N0 takes the text this system
actually receives - the RSS title and summary - and produces one canonical text with
paragraph and sentence spans, plus an index map back to the raw HTML. Later nodes read this
object and nothing else, so nobody re-normalises the text and ends up with different offsets.

The canonical text is deliberately the same text `schema._normalize` produces: tags become a
space, entities are decoded, curly quotes are folded, whitespace is collapsed, the result is
lower-cased. That is what the evidence locator already stores and searches, so an offset
reported by N1 means the same thing as an offset reported by `schema._locate`.

Note what N0 does not have: the full article. RSS gives a title and a summary, full-text fetch
is disabled, so that is the entire input. The pipeline's recall ceiling is the recall of this
text and no node can exceed it.
"""
from __future__ import annotations

import hashlib
import re
from html import unescape

VERSION = 'n0-v1'

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


def _text_of(article, name):
    if article is None:
        return ''
    if isinstance(article, dict):
        return str(article.get(name) or '')
    return str(getattr(article, name, '') or '')


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


def normalise(raw):
    """(text, spans): the canonical text and, per character, its span in `raw`."""
    chars, spans = _drop_tags(str(raw or ''))
    chars, spans = _decode_entities(chars, spans)
    return _canonicalise(chars, spans)


def _paragraph_spans(raw):
    """Raw spans of the paragraphs in `raw`, split at block tags. Empty ones are dropped."""
    spans, last = [], 0
    for match in _BLOCK.finditer(raw):
        if raw[last:match.start()].strip():
            spans.append((last, match.start()))
        last = match.end()
    if raw[last:].strip():
        spans.append((last, len(raw)))
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
    """One input field (title or summary) with its text, raw spans and structure."""

    def __init__(self, name, text, spans, global_start, raw_start, raw_end):
        self.name = name
        self.text = text
        self.spans = spans
        self.global_start = global_start
        self.raw_start = raw_start
        self.raw_end = raw_end

    def raw_span(self, start, end):
        """The span in the raw HTML that the canonical text[start:end] came from."""
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

    def __init__(self, fields, segments, sentences, source_hash):
        self.fields = fields
        self.segments = segments
        self.sentences = sentences
        self.text = ' '.join(f.text for f in fields.values() if f.text)
        self.source_hash = source_hash
        self.text_hash = hashlib.sha256(self.text.encode('utf-8')).hexdigest()

    def field(self, name):
        field = self.fields.get(name)
        if field is None:
            raise KeyError(f'no field named {name!r}')
        return field

    def segment_of(self, field_name, start):
        """Index into `segments` of the paragraph containing `start` in `field_name`."""
        for segment in self.segments:
            if segment['field'] == field_name and segment['start'] <= start < segment['end']:
                return segment['index']
        return None

    def sentence_of(self, field_name, start):
        """Index into `sentences` of the sentence containing `start` in `field_name`."""
        for sentence in self.sentences:
            if sentence['field'] == field_name and sentence['start'] <= start < sentence['end']:
                return sentence['index']
        return None

    def raw_span(self, field_name, start, end):
        return self.field(field_name).raw_span(start, end)

    def to_dict(self):
        counts = {name: len(field.text) for name, field in self.fields.items()}
        return {
            'version': VERSION,
            'source_hash': self.source_hash,
            'text_hash': self.text_hash,
            'text': self.text,
            'fields': {name: field.to_dict() for name, field in self.fields.items()},
            'segments': self.segments,
            'sentences': self.sentences,
            'stats': {'characters': len(self.text), 'field_characters': counts,
                      'segments': len(self.segments), 'sentences': len(self.sentences)},
        }


def build(article):
    """Normalise one article. Raises ValueError when there is no text to normalise."""
    title_raw = _text_of(article, 'title')
    summary_raw = _text_of(article, 'summary')
    if not title_raw.strip() and not summary_raw.strip():
        raise ValueError('article has no title or summary text')
    source_hash = hashlib.sha256(
        (title_raw + '\x00' + summary_raw).encode('utf-8')).hexdigest()

    raw_fields = {'title': [(0, len(title_raw))] if title_raw.strip() else [],
                  'summary': _paragraph_spans(summary_raw)}
    fields, segments, sentences = {}, [], []
    global_cursor = 0
    for name in ('title', 'summary'):
        raw = title_raw if name == 'title' else summary_raw
        chars, spans, paragraph_texts = [], [], []
        for raw_start, raw_end in raw_fields[name]:
            text, local_spans = normalise(raw[raw_start:raw_end])
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
            paragraph = len([s for s in segments if s['field'] == name])
            segments.append({
                'index': len(segments), 'field': name, 'paragraph': paragraph,
                'start': start, 'end': end,
                'global_start': global_cursor + start, 'global_end': global_cursor + end,
                'raw_start': raw_start, 'raw_end': raw_end, 'text': text,
            })
            for sentence_start, sentence_end in sentence_spans(text):
                sentences.append({
                    'index': len(sentences), 'segment': len(segments) - 1, 'field': name,
                    'start': start + sentence_start, 'end': start + sentence_end,
                    'global_start': global_cursor + start + sentence_start,
                    'global_end': global_cursor + start + sentence_end,
                    'text': text[sentence_start:sentence_end],
                })
        global_cursor += len(field_text) + 1
    if not fields:
        raise ValueError('article has no title or summary text')
    return ArticleText(fields, segments, sentences, source_hash)
