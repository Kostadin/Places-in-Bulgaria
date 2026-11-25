"""Shared paths and loaders for build.py and download.py.

verify.py deliberately does NOT import this module, so that verification
does not reuse any of the logic that produced the data.
"""
import collections
import glob
import json
import math
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, 'Places-in-Bulgaria.json')
DL = os.path.join(ROOT, 'downloads')

# The capital and the surrounding oblast are named differently in this file and in EKATTE.
OBL_REPO = {'SOF': 'София', 'SFO': 'София област'}


def utf8_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass


def need(path, what, hint=''):
    if not os.path.exists(path):
        sys.exit(f'Missing {what}: {path}\n{hint}Run first:  python3 tools/download.py')
    return path


def find_one(pattern, what):
    hits = sorted(glob.glob(os.path.join(DL, pattern)))
    if not hits:
        sys.exit(f'Missing {what} ({pattern} in {DL}).\nRun first:  python3 tools/download.py')
    return hits[-1]


# ---------------------------------------------------------------- this repository's file
def load_repo(path=DATA_FILE):
    """Returns (raw dict, flat dict keyed by the 5-digit EKATTE code)."""
    d = json.load(open(path, encoding='utf-8'))
    out = {}
    for o, ms in d.items():
        for m, ps in ms.items():
            for e, p in ps.items():
                out[e.zfill(5)] = dict(p, oblast=o, obshtina=m, key=e)
    return d, out


# ---------------------------------------------------------------- NSI EKATTE register
def load_ekatte():
    """Returns (settlements, municipalities, oblasts, kmetstva) keyed by their codes."""
    base = find_one('ekatte/ek_atte.json', 'EKATTE register')
    base = os.path.dirname(base)

    def rows(n):  # the last row of every NSI file is metadata, not a record
        return [r for r in json.load(open(os.path.join(base, n + '.json'), encoding='utf-8-sig')) if 'name' in r]
    atte = {r['ekatte']: r for r in rows('ek_atte') if r.get('ekatte', '').isdigit()}
    obst = {r['obshtina']: r for r in rows('ek_obst')}
    obl = {r['oblast']: r for r in rows('ek_obl')}
    kmet = {r['kmetstvo']: r for r in rows('ek_kmet')}
    return atte, obst, obl, kmet


# ---------------------------------------------------------------- NSI official settlement points
def gpkg_table(con):
    return con.execute("select table_name from gpkg_contents where data_type='features'").fetchone()[0]


def load_points():
    """EKATTE -> {'xcoord': lon, 'ycoord': lat, ...} (WGS84)."""
    con = sqlite3.connect(find_one('spatial/SU_BG_NSI_NM_*.gpkg', 'NSI settlement points'))
    con.row_factory = sqlite3.Row
    return {r['Identifier']: dict(r) for r in con.execute(f'select * from "{gpkg_table(con)}"')}


# ---------------------------------------------------------------- OpenStreetMap / Econt
def load_osm():
    d = json.load(open(need(os.path.join(DL, 'osm', 'osm_places.json'), 'OpenStreetMap places'), encoding='utf-8'))
    out = {}
    for x in d['elements']:
        e = x['tags'].get('ekatte', '').strip()
        if e.isdigit():
            out.setdefault(e.zfill(5), []).append((x['lat'], x['lon'], x['tags'].get('name'), x['tags'].get('place')))
    return out


def load_econt():
    d = json.load(open(need(os.path.join(DL, 'econt', 'cities.json'), 'Econt city list'), encoding='utf-8'))['cities']
    out = {}
    for c in d:
        out.setdefault((c['regionName'], c['name']), []).append(c)
    return out


def dist_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    h = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- CRC postcode index (text from the PDF)
OBLASTS = ['Благоевград', 'Бургас', 'Варна', 'Велико Търново', 'Видин', 'Враца', 'Габрово', 'Добрич', 'Кърджали',
           'Кюстендил', 'Ловеч', 'Монтана', 'Пазарджик', 'Перник', 'Плевен', 'Пловдив', 'Разград', 'Русе', 'Силистра',
           'Сливен', 'Смолян', 'София', 'Стара Загора', 'Търговище', 'Хасково', 'Шумен', 'Ямбол']


def load_crc():
    """Parses the CRC index.

    sec1: list of (code, settlement, municipality, oblast) from part 1 (one base code per settlement).
    sec2: {(oblast, locality): Counter(code -> number of street rows)} from part 2 (street-level codes).
    """
    L = open(need(os.path.join(DL, 'post', 'crc2016.txt'), 'CRC postcode index (text)',
             'It is made from the PDF by Ghostscript; install Ghostscript (see README).\n'), encoding='utf-8').read().split('\n')
    split = next(i for i, l in enumerate(L) if 'административен' in l and 'пощ.' in l)
    rx1 = re.compile(r'^\s*(\d{4})\s{2,}(\S.*?)\s{2,}(\S.*?)\s{2,}(\S.*?)\s*$')
    rx1c = re.compile(r'^\s*(\d{4})\s{2,}(\S.*?)\s{2,}(\S.*?)\s*$')  # oblast centres: code, name, oblast
    sec1 = []
    for l in L[:split]:
        m = rx1.match(l)
        if m:
            sec1.append(m.groups())
            continue
        m = rx1c.match(l)
        if m and m.group(2) == m.group(3):
            sec1.append((m.group(1), m.group(2), m.group(2), m.group(3)))
    obl_alt = '|'.join(sorted(map(re.escape, OBLASTS), key=len, reverse=True))
    rx_obl = re.compile(r'^\s*(%s)\s*$' % obl_alt)
    rx2 = re.compile(r'^\s*(?:(%s)\s+)?(\d{4})\s+(\S.*?)(?:\s{2,}|$)' % obl_alt)
    sec2 = collections.defaultdict(collections.Counter)
    cur = None
    for l in L[split:]:
        m = rx_obl.match(l)
        if m:
            cur = m.group(1)
            continue
        m = rx2.match(l)
        if m:
            sec2[(m.group(1) or cur, m.group(3).strip())][m.group(2)] += 1
    return sec1, sec2
