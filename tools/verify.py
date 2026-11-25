"""Independent check of Places-in-Bulgaria.json against the raw official sources.

Usage:
  python3 tools/verify.py                 check Places-in-Bulgaria.json
  python3 tools/verify.py OTHER.json      check another file (e.g. an older version)
  python3 tools/verify.py --quiet         do not list the border cases

Run tools/download.py first. This script does not import build.py, postcodes.py or common.py:
it reads the downloaded files directly, so a mistake in the build logic cannot hide itself.
Each check prints PASS or FAIL with details; the exit code is the number of failed checks.
"""
import collections, difflib, glob, json, math, os, re, sqlite3, struct, sys
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding='utf-8')
    except Exception: pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(ROOT, 'downloads')
args = [a for a in sys.argv[1:] if not a.startswith('--')]
path = args[0] if args else os.path.join(ROOT, 'Places-in-Bulgaria.json')
QUIET = '--quiet' in sys.argv
def src(pattern):
    hits = sorted(glob.glob(os.path.join(DL, pattern)))
    if not hits: sys.exit(f'Missing {pattern} in {DL}.\nRun first:  python3 tools/download.py')
    return hits[-1]
raw = open(path, encoding='utf-8').read(); D = json.loads(raw)
print('Checking', os.path.relpath(path), '\n')
R = collections.OrderedDict()
def check(name, ok, detail=''):
    R[name] = (ok, detail); print(('PASS ' if ok else 'FAIL ') + name + (' — ' + str(detail) if detail else ''))
def skip(name, why):
    R[name] = (None, why); print('SKIP ' + name + ' — ' + why)

# ---------------- raw sources ----------------
# the last row of every NSI file is metadata, hence the 'name' filter
EK = [r for r in json.load(open(src('ekatte/ek_atte.json'), encoding='utf-8-sig')) if 'name' in r]
EK = {r['ekatte']: r for r in EK if r['ekatte'].isdigit()}
OBST = {r['obshtina']: r for r in json.load(open(src('ekatte/ek_obst.json'), encoding='utf-8-sig')) if 'name' in r}
KMET = {r['kmetstvo']: r for r in json.load(open(src('ekatte/ek_kmet.json'), encoding='utf-8-sig')) if 'name' in r}
def table(con): return con.execute("select table_name from gpkg_contents where data_type='features'").fetchone()[0]
c = sqlite3.connect(src('spatial/SU_BG_NSI_NM_*.gpkg'))
PT = {i: (y, x) for i, x, y in c.execute(f'select Identifier, xcoord, ycoord from "{table(c)}"')}
OSM = collections.defaultdict(list)
for x in json.load(open(src('osm/osm_places.json'), encoding='utf-8'))['elements']:
    e = x['tags'].get('ekatte', '').strip()
    if e.isdigit(): OSM[e.zfill(5)].append((x['lat'], x['lon']))
ECONT = collections.defaultdict(list)
for x in json.load(open(src('econt/cities.json'), encoding='utf-8'))['cities']:
    ECONT[(x['regionName'], x['name'])].append(x['postCode'])
_crc = os.path.join(DL, 'post', 'crc2016.txt')
CRC = open(_crc, encoding='utf-8').read().split('\n') if os.path.exists(_crc) else None

def hav(a, b, c_, d):
    p = math.pi / 180
    h = math.sin((c_ - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c_ * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))

# ---- forward transverse mercator (GRS80, UTM 35N) — Krüger series ----
A_, F_ = 6378137.0, 1 / 298.257222101
n = F_ / (2 - F_); A = A_ / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
al = [n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240]
e2 = F_ * (2 - F_); e = math.sqrt(e2)
def utm(lat, lon, k0=0.9996, lon0=27, FE=500000):
    phi, lam = math.radians(lat), math.radians(lon - lon0)
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi = math.atan2(t, math.cos(lam)); eta = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(al[j] * math.cos(2 * (j + 1) * xi) * math.sinh(2 * (j + 1) * eta) for j in range(3))
    y = xi + sum(al[j] * math.sin(2 * (j + 1) * xi) * math.cosh(2 * (j + 1) * eta) for j in range(3))
    return FE + k0 * A * x, k0 * A * y

# ---- GeoPackage multipolygon parsing ----
def parse_gpkg(b):
    flags = b[3]; env = (flags >> 1) & 7; off = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    return parse_wkb(b, off)[0]
def parse_wkb(b, o):
    bo = '<' if b[o] == 1 else '>'; typ = struct.unpack(bo + 'I', b[o + 1:o + 5])[0] % 1000; o += 5
    if typ == 3:
        nr = struct.unpack(bo + 'I', b[o:o + 4])[0]; o += 4; rings = []
        for _ in range(nr):
            np_ = struct.unpack(bo + 'I', b[o:o + 4])[0]; o += 4
            rings.append(struct.unpack(bo + 'd' * 2 * np_, b[o:o + 16 * np_])); o += 16 * np_
        return [rings], o
    if typ == 6:
        k = struct.unpack(bo + 'I', b[o:o + 4])[0]; o += 4; polys = []
        for _ in range(k):
            p, o = parse_wkb(b, o); polys += p
        return polys, o
    raise ValueError(typ)
def in_ring(x, y, r):
    ins = False; m = len(r) // 2
    for i in range(m):
        x1, y1, x2, y2 = r[2 * i], r[2 * i + 1], r[2 * ((i + 1) % m)], r[2 * ((i + 1) % m) + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: ins = not ins
    return ins
def in_mpoly(x, y, polys): return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in polys)
def ring_dist(x, y, polys):
    best = 1e18
    for p in polys:
        for r in p:
            m = len(r) // 2
            for i in range(m - 1):
                x1, y1, x2, y2 = r[2 * i], r[2 * i + 1], r[2 * i + 2], r[2 * i + 3]
                dx, dy = x2 - x1, y2 - y1; L = dx * dx + dy * dy
                t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L)) if L else 0
                best = min(best, (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2)
    return math.sqrt(best)
lc = sqlite3.connect(src('spatial/SU_BG_NSI_LAU_*.gpkg'))
LAU = {}; LAU_NAME = {}
for ident, name, dist, blob in lc.execute(f'select Identifier, Name, DistrictCode, Shape from "{table(lc)}"'):
    LAU[ident] = parse_gpkg(blob); LAU_NAME[(dist, name)] = ident
# sanity of projection: NSI points must fall inside their own NSI municipality polygons
own = sum(in_mpoly(*utm(*PT[k]), LAU[EK[k]['obshtina']]) for k in PT)

# ---------------- flatten file ----------------
OBL_REPO = {'SOF': 'София', 'SFO': 'София област'}
OBL_NAME = {r['oblast']: OBL_REPO.get(r['oblast'], r['oblast_name'].replace('обл. ', '')) for r in EK.values()}
flat = {}
for o, ms in D.items():
    for m, ps in ms.items():
        for k, p in ps.items(): flat[k] = dict(p, oblast=o, obshtina=m)
settl = {k.zfill(5): p for k, p in flat.items() if p['type'] != 'к.к.'}
resorts = {k: p for k, p in flat.items() if p['type'] == 'к.к.'}

# ---------------- checks ----------------
check('format: re-serialises byte-identically (indent=2, UTF-8, sorted)', json.dumps(D, ensure_ascii=False, indent=2) + '\n' == raw and
      all(list(ms) == sorted(ms) for ms in D.values()) and list(D) == sorted(D))
check('schema: every record has exactly the 7 documented fields',
      all(set(p) - {'oblast', 'obshtina'} == {'name', 'type', 'town_hall', 'phone_code', 'latitude', 'longitude', 'post_codes'} for p in flat.values()))
check('projection sanity: NSI points inside their NSI municipality polygon', own >= len(PT) - 5, f'{own}/{len(PT)}')
miss = set(EK) - set(settl); extra = set(settl) - set(EK)
check('coverage: settlements == official EKATTE list (5256)', not miss and not extra, f'missing={sorted(miss)} extra={sorted(extra)} file={len(settl)} resorts kept={len(resorts)}')
bad = [(k, p['name'], EK[k]['name']) for k, p in settl.items() if k in EK and p['name'] != EK[k]['name']]
check('names match EKATTE', not bad, bad[:10])
bad = [(k, p['name'], p['type'], EK[k]['t_v_m']) for k, p in settl.items() if k in EK and p['type'] != EK[k]['t_v_m']]
check('types (гр./с./ман.) match EKATTE', not bad, bad[:10])
bad = [(k, p['name'], p['oblast'], p['obshtina']) for k, p in settl.items() if k in EK and (p['oblast'], p['obshtina']) != (OBL_NAME[EK[k]['oblast']], EK[k]['obshtina_name'])]
check('oblast + municipality match EKATTE', not bad, bad[:10])
def exp_th(r):
    if r['kmetstvo'].endswith('-00'):
        return 'Столична' if r['obshtina'] == 'SOF46' else EK[OBST[r['obshtina']]['ekatte']]['name']
    return KMET[r['kmetstvo']]['name']
bad = [(k, p['name'], p['town_hall'], exp_th(EK[k])) for k, p in settl.items() if k in EK and p['town_hall'] != exp_th(EK[k])]
check('town_hall matches EKATTE kmetstvo (municipal centre when none)', not bad, bad[:10])

# coordinates
muni_id = {}
for r in EK.values(): muni_id[(OBL_NAME[r['oblast']], r['obshtina_name'])] = r['obshtina']
pip_fail = []
for k, p in flat.items():
    mid = muni_id.get((p['oblast'], {'Бобовдол': 'Бобов дол'}.get(p['obshtina'], p['obshtina'])))
    if mid is None: pip_fail.append((k, p['name'], p['obshtina'], 999)); continue
    x, y = utm(p['latitude'], p['longitude'])
    if not in_mpoly(x, y, LAU[mid]):
        pip_fail.append((k, p['name'], p['obshtina'], round(ring_dist(x, y, LAU[mid]) / 1000, 2)))
far = [f for f in pip_fail if f[3] > 0.5]
check('every coordinate lies inside (or <0.5 km from) its municipality polygon [NSI LAU 2024]', not far,
      f'outside={len(pip_fail)} (farthest {max([f[3] for f in pip_fail] or [0])} km from the border) far={far[:10]}')
if pip_fail and not QUIET: print('   border cases:', pip_fail)
near = []
for k, p in settl.items():
    if k not in PT: continue  # not an official settlement; already reported by the coverage check
    dn = hav(p['latitude'], p['longitude'], *PT[k])
    do = min([hav(p['latitude'], p['longitude'], a, b) for a, b in OSM.get(k, [])] or [1e9])
    if min(dn, do) > 1: near.append((k, p['name'], round(dn, 2), round(do, 2)))
check('every coordinate within 1 km of the NSI point or the OSM node with the same EKATTE', not near, near[:10])
dup = collections.defaultdict(list)
for k, p in flat.items(): dup[(p['latitude'], p['longitude'])].append(p['name'])
dups = [v for v in dup.values() if len(v) > 1]
check('no two places share identical coordinates (issue #3)', not dups, dups[:10])

# postcodes vs raw CRC text: code must appear on a line together with the place name (or a known former name)
crc_by_code = collections.defaultdict(list)
for l in CRC or []:
    for cd in re.findall(r'(?<!\d)(\d{4})(?!\d)', l): crc_by_code[cd].append(l)
ALIASES = {'Бов': ['Гара Бов'], 'Лакатник': ['Гара Лакатник'], 'Орешец': ['Гара Орешец', 'Орешица'], 'Хитрино': ['Гара Хитрино'],
           'Елин Пелин': ['Гара Елин Пелин'], 'Завет': ['Гара Завет'], 'Каспичан': ['Каспичан село'], 'Костенец': ['Костенец село'],
           'Гащевци': ['Гашевци'], 'Градина': ['Стефан Стамболово'], 'Мосомище': ['Мусомища'], 'Стара Загора': ['Стара'],
           'Бургас': ['Банево', 'Ветрен', 'Рудник', 'Мина Черно море', 'Бургаски мин. бани'], 'Поморие': ['Каменар'],
           'Горна Оряховица': ['Гара Горна Оряховица'], 'Свиленград': ['Гара Свиленград'], 'Симеоновград': ['Гара Симеоновград'],
           'Ямбол': ['Гара Ямбол'], 'Пазарджик': ['Гара Пазарджик'], 'Търговище': ['Гара Търговище'], 'Бяла': ['Гара Бяла'],
           'София': ['София', '']}
def nm(s): return re.sub(r'[\s\-]+', ' ', s.lower().replace('e', 'е'))
pc_bad = []; econt_override = []
for k, p in settl.items():
    names = [p['name']] + ALIASES.get(p['name'], [])
    for cd in p['post_codes']:
        lines = crc_by_code.get(cd, [])
        ok = any(nm(a) in nm(l) for a in names if a for l in lines) or (p['name'] == 'София' and cd.startswith('1') and lines)
        if not ok:
            o = 'София Област' if p['oblast'] == 'София област' else p['oblast']
            if cd in ECONT.get((o, p['name']), []): econt_override.append((p['name'], cd)); continue
            # fuzzy spelling variant in CRC (e.g. Войняговци/Войнеговци)
            if any(difflib.SequenceMatcher(None, nm(p['name']), nm(w)).ratio() >= 0.8 for l in lines for w in re.split(r'\s{2,}', l.strip())):
                continue
            pc_bad.append((k, p['name'], p['obshtina'], cd))
if CRC is None:
    skip('every postcode is backed by the CRC index row for that place (or Econt live data)',
         'downloads/post/crc2016.txt missing - install Ghostscript and run tools/download.py again')
else:
    check('every postcode is backed by the CRC index row for that place (or Econt live data)', not pc_bad,
          f'unbacked={pc_bad[:15]}; econt-backed={econt_override}')
check('issue #2: 1415 (Драгалевци quarter) listed under София', '1415' in flat['68134']['post_codes'])
nocode = [p['name'] for p in settl.values() if not p['post_codes']]
check('every settlement has at least one postcode', not nocode, nocode[:10])
agree = dis = 0; dl = []
namecount = collections.Counter((p['oblast'], p['name']) for p in settl.values())
for k, p in settl.items():
    o = 'София Област' if p['oblast'] == 'София област' else p['oblast']
    m = ECONT.get((o, p['name']))
    if m and len(m) == 1 and len(m[0]) == 4 and namecount[(p['oblast'], p['name'])] == 1:
        if m[0] in p['post_codes']: agree += 1
        else: dis += 1; dl.append((p['name'], p['obshtina'], p['post_codes'][:3], m[0]))
check('postcodes agree with Econt live courier data wherever Econt lists the place (unambiguous names)', dis == 0, f'agree={agree} disagree={dis} {dl[:15]}')

failed = sum(ok is False for ok, _ in R.values())
skipped = sum(ok is None for ok, _ in R.values())
print('\nSUMMARY:', sum(ok is True for ok, _ in R.values()), '/', len(R), 'checks passed',
      f'({failed} failed, {skipped} skipped)' if failed or skipped else '')
sys.exit(failed)
