"""Catalogue vocabulary, directional uses and unit-aware variant matching."""
import os
import re
from collections import defaultdict
from functools import lru_cache

from rapidfuzz.fuzz import WRatio


def fold(text):
    return ' '.join(text.casefold().replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').split())


COLOURS = ('schwarz', 'weiss', 'natur', 'silber', 'gold', 'braun', 'rot', 'blau', 'gruen', 'grau')
COLOUR = re.compile(r'\b(' + '|'.join(COLOURS) + r')(?:e[rmns]?)?\b')
SHADE = 'Schattenfugenrahmen'
USES = {SHADE: ('Außenrahmen für auf Keilrahmen gespannte Leinwand',)}
OUTER = re.compile(r'\b(?:aussenrahmen|(?:bilder)?rahmen)\b.{0,55}\b(?:fuer|um)\b.{0,45}\b(?:keilrahmen|leinwand)')
SKIP_WORDS = {'bsp', 'set', 'stueck', 'der', 'die', 'das', 'fuer', 'mit', 'ohne'}


def seeks_outer_frame(text):
    match = OUTER.search(fold(text))
    return bool(match and not re.search(r'\b(?:fuer|um|zum|am|vom)\b', fold(text)[:match.start()]))


def colour(text):
    match = COLOUR.search(fold(text))
    return match[1] if match else ''


def classify(name, extra='', matchcode=''):
    # Prefer the product head. An accessory "für Schattenfugenrahmen" has its own family.
    head = re.split(r'\b(?:für|fuer|zum|fürs)\b', name, maxsplit=1, flags=re.I)[0]
    words = re.findall(r'[^\W\d_][^\W\d_\-]*', head)
    for word in words:
        token = fold(word)
        if len(token) < 3 or token in SKIP_WORDS or COLOUR.fullmatch(token) or token in ('folierte', 'folierter', 'foliertes'):
            continue
        if token.startswith('schattenfug'):
            return SHADE
        if token.startswith('keilrahmenleist'):
            return 'Keilrahmenleiste'
        if token in ('leiste', 'profil', 'rahmen') and re.match(r'\s*schattenfug', extra or matchcode, re.I):
            return SHADE
        return word.capitalize()
    return ''


def vocabulary(conn, category=''):
    scope = ' AND category=?' if category else ''
    groups = conn.execute("SELECT family, count(*) AS n FROM articles WHERE family != ''" +
                          scope + ' GROUP BY family ORDER BY n DESC, family', (category,) if category else ())
    aliases = defaultdict(list)
    for family, term in conn.execute('SELECT family,term FROM family_terms ORDER BY term'):
        aliases[family].append(term)
    return {family: (*USES.get(family, ()), *aliases[family]) for family, _ in groups}


def intent(query, vocab):
    text = fold(query)
    if SHADE in vocab and seeks_outer_frame(text):
        return {SHADE}
    hits = set()
    for family, aliases in vocab.items():
        if any(re.search(r'(?<!\w)' + re.escape(fold(phrase)) + r'(?!\w)', text) for phrase in aliases):
            hits.add(family)
    if hits:
        return hits
    # Use the sought product before "für", not the product mentioned as its application.
    head = re.split(r'\b(?:fuer|um)\b', text, maxsplit=1)[0]
    words = set(re.findall(r'\w+', head))
    return {family for family in vocab if fold(family) in words or
            (family == SHADE and any(w.startswith('schattenfug') for w in words))}


def shortlist(conn, query, vocab, wanted, category):
    text = fold(query)
    def relevance(family):
        names = (family, *vocab[family])
        return (family in wanted, max(WRatio(text, fold(name)) for name in names))
    ordered = sorted(vocab, key=relevance, reverse=True)[:12]
    options = []
    for family in ordered:
        sql = 'SELECT DISTINCT name FROM articles WHERE family=?'
        args = (family,)
        if category:
            sql += ' AND category=?'
            args += (category,)
        examples = [r[0][:120] for r in conn.execute(sql + ' LIMIT 2', args)]
        options.append({'name':family, 'beispiele':examples, 'verwendungen':[a[:120] for a in vocab[family][:4]]})
    return options


NUM = r'\d+(?:[.,]\d+)?'
AXIS = rf'({NUM})\s*(mm|cm|m)?'
PAIR = re.compile(rf'(?<![\w.,]){AXIS}\s*[x×*/]\s*{AXIS}(?!\w)', re.I)
SINGLE = re.compile(rf'(?<![\w.,])({NUM})\s*(mm|cm|m)\b', re.I)
THREAD = re.compile(rf'\bm({NUM})\s*[x×*/]\s*{AXIS}(?!\w)', re.I)
ROLE = re.compile(r'(aussenmass|format|bildmass|profilmass|profilbreite|profil|breite|höhe|länge)\s*[:=]?\s*$', re.I)
COLUMN_UNIT = os.getenv('CATALOG_DIMENSION_UNIT', '').strip().lower()
if COLUMN_UNIT not in ('', 'mm', 'cm', 'm'):
    raise ValueError('CATALOG_DIMENSION_UNIT muss leer, mm, cm oder m sein.')


def quantity(number, unit):
    return round(float(number.replace(',', '.')) * {'mm': 1, 'cm': 10, 'm': 1000, '': 1}[unit], 4)


def role(text, default):
    m = ROLE.search(text)
    if not m:
        return default
    return {'laenge': 'length', 'breite': 'width', 'profilbreite': 'width', 'hoehe': 'height',
            'profil': 'profile', 'profilmass': 'profile', 'aussenmass':'outer'}.get(fold(m[1]), 'format')


@lru_cache(maxsize=20000)
def measures(text, family=''):
    """Keep unitless values separate. Do not mistake profile dimensions for picture format."""
    text = text.casefold()
    values = set()
    for match in THREAD.finditer(text):
        diameter, length, unit = match.groups()
        values.add(('thread', True, (quantity(diameter, 'mm'), quantity(length, unit or 'mm'))))
    text = THREAD.sub(' ', text)
    end = 0
    for match in PAIR.finditer(text):
        a, u, b, v = match.groups()
        default = {'Keilrahmenleiste':'profile', SHADE:'format'}.get(family, 'pair')
        kind = role(text[end:match.start()], default)
        values.add((kind, bool(u or v), (quantity(a, u or v or ''), quantity(b, v or u or ''))))
        end = match.end()
    without_pairs = PAIR.sub(' ', text)
    for match in SINGLE.finditer(without_pairs):
        kind = role(without_pairs[:match.start()], 'length' if family == 'Keilrahmenleiste' else 'single')
        values.add((kind, True, (quantity(*match.groups()),)))
    return frozenset(values)


@lru_cache(maxsize=20000)
def article_measures(name, extra, family, width, height, length, column_unit):
    values = set(measures(name, family) | measures(extra, family))
    axes = {}
    for kind, raw in (('width', width), ('height', height), ('length', length)):
        match = re.fullmatch(rf'\s*{AXIS}\s*', raw.casefold())
        if match:
            n, u = match.groups()
            u = u or column_unit
            axes[kind] = (bool(u), quantity(n, u or ''))
            values.add((kind, bool(u), (axes[kind][1],)))
    if 'width' in axes and 'height' in axes and axes['width'][0] == axes['height'][0]:
        values.add(('profile' if family == 'Keilrahmenleiste' else 'pair', axes['width'][0],
                    (axes['width'][1], axes['height'][1])))
    return values


def measure_score(requested, row):
    if not requested:
        return 0
    actual = article_measures(*(row[k] for k in ('name','extra','family','width','height','length')), COLUMN_UNIT)
    score = 0
    for kind, unit, size in requested:
        candidates = [v for r, u, v in actual if u == unit and
                      (r == kind or (kind == 'single' and len(v) == 1)
                       or (kind == 'pair' and len(v) == 2 and r != 'thread'))]
        if size in candidates:
            score += 2
        elif candidates:
            score -= 1
    return score


def variant_key(row):
    if not row['family']:
        return ()
    def model_text(value):
        return ' '.join(SINGLE.sub(' ', PAIR.sub(' ', fold(value))).split()).strip(' ,-/')
    return (row['family'], row['category'], model_text(row['name']), model_text(row['extra']), row['unit'])


def prepare_results(rows, query):
    """Keep ranked group positions, put the best-fitting measured variant on its card."""
    positions = defaultdict(list)
    for index, row in enumerate(rows):
        key = variant_key(row)
        row['variant_key'] = key
        if key and measures(query, row['family']):
            positions[key].append(index)
        row.pop('hash', None)
        row.pop('search_text', None)
    for indices in positions.values():
        if len(indices) < 2:
            continue
        requested = measures(query, rows[indices[0]]['family'])
        variants = sorted((rows[i] for i in indices), key=lambda r:measure_score(requested, r), reverse=True)
        for i, variant in zip(indices, variants):
            rows[i] = variant
