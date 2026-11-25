"""Rebuilds Places-in-Bulgaria.json from the official sources.

Usage:
  python3 tools/build.py                 rebuild Places-in-Bulgaria.json in place
  python3 tools/build.py --check         only report what would change (exit code 1 if anything would)
  python3 tools/build.py IN.json OUT.json  read IN.json, write OUT.json

Run tools/download.py first. The list of every change is written to downloads/changelog.json.

Rules (applied to every settlement in the EKATTE register):
  name, type, oblast, municipality  from EKATTE
  town_hall    the kmetstvo from EKATTE; for places without one, the municipal centre
               ("Столична" for Sofia)
  coordinates  kept if within 1 km of the NSI point or of the OpenStreetMap node with the
               same EKATTE code; otherwise replaced by the NSI point (4 decimals)
  post_codes   from the CRC index (see postcodes.py); when Econt's live data and the existing
               file agree on a code that differs from a single CRC code, that code is kept
  phone_code   kept as it is (there is no official per-settlement list); empty for new places
Settlements missing from EKATTE are removed, except the к.к. resort entries, which are kept.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_FILE, DL, OBL_REPO, dist_km, load_econt, load_ekatte, load_osm, load_points, load_repo, utf8_console  # noqa: E402
from postcodes import build_postcode_map  # noqa: E402

# Coordinates replaced even though they are within 1 km of a reference:
#  12615 Вълчовци (Елена): the OSM ekatte tags of the two Вълчовци villages are swapped
#  72360 Тешел, 35345 Каленовци: the old point is just outside the municipality border; the NSI point is inside
FORCE_COORD = {'12615', '72360', '35345'}
FIELDS = ('name', 'type', 'town_hall', 'phone_code', 'latitude', 'longitude', 'post_codes')


def build(src):
    atte, obst, obl, kmet = load_ekatte()
    pts, osm, ec = load_points(), load_osm(), load_econt()
    d, repo = load_repo(src)
    codes, unplaced, conflicts = build_postcode_map(atte, obl)
    log = collections.defaultdict(list)
    log['postcode_rows_not_placed'] = unplaced
    log['postcode_conflicts'] = conflicts

    def repo_obl(r):
        return OBL_REPO.get(r['oblast'], obl[r['oblast']]['name'])

    def osm_dist(e, lat, lon):
        return min(dist_km(lat, lon, a, b) for a, b, _, _ in osm[e]) if e in osm else None

    def econt_rec(r):
        o = 'София Област' if r['oblast'] == 'SFO' else ('София' if r['oblast'] == 'SOF' else obl[r['oblast']]['name'])
        m = ec.get((o, r['name']))
        return m[0] if m and len(m) == 1 else None

    def final_postcodes(e):
        cs = set(codes[e])
        old = set(repo[e]['post_codes']) if e in repo else set()
        m = econt_rec(atte[e])
        if m and m['postCode'] not in cs and m['postCode'] in old and len(cs) == 1:
            log['postcode_econt_override'].append((e, atte[e]['name'], sorted(cs), m['postCode']))
            cs = {m['postCode']}
        return sorted(cs)

    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for e, r in atte.items():
        p = repo.get(e)
        o, m = repo_obl(r), r['obshtina_name']
        q = pts[e]
        if r['kmetstvo'].endswith('-00'):
            th = 'Столична' if r['obshtina'] == 'SOF46' else atte[obst[r['obshtina']]['ekatte']]['name']
        else:
            th = kmet[r['kmetstvo']]['name']
        pc = final_postcodes(e)
        nsi = (round(q['ycoord'], 4), round(q['xcoord'], 4))
        if p is None:
            rec = {'name': r['name'], 'type': r['t_v_m'], 'town_hall': th, 'phone_code': '',
                   'latitude': nsi[0], 'longitude': nsi[1], 'post_codes': pc}
            log['added'].append((e, r['t_v_m'], r['name'], o, m))
            key = str(int(e))
        else:
            key = p['key']
            lat, lon = p['latitude'], p['longitude']
            dn = dist_km(lat, lon, q['ycoord'], q['xcoord'])
            do = osm_dist(e, lat, lon)
            if (e in FORCE_COORD and (lat, lon) != nsi) or (dn > 1 and (do is None or do > 1)):
                log['coords'].append((e, r['name'], m, (lat, lon), nsi, round(dn, 1)))
                lat, lon = nsi
            if p['name'] != r['name']:
                log['name'].append((e, p['name'], r['name']))
            if p['type'] != r['t_v_m']:
                log['type'].append((e, r['name'], p['type'], r['t_v_m']))
            if (p['oblast'], p['obshtina']) != (o, m):
                log['moved'].append((e, r['name'], (p['oblast'], p['obshtina']), (o, m)))
            if p['town_hall'] != th:
                log['town_hall'].append((e, r['name'], m, p['town_hall'], th))
            if sorted(p['post_codes']) != pc:
                log['post_codes'].append((e, r['name'], m, p['post_codes'], pc))
            rec = {'name': r['name'], 'type': r['t_v_m'], 'town_hall': th, 'phone_code': p['phone_code'],
                   'latitude': lat, 'longitude': lon, 'post_codes': pc}
        out[o][m][key] = rec

    for e, p in repo.items():
        if e in atte:
            continue
        if p['type'] == 'к.к.':
            out[p['oblast']][p['obshtina']][p['key']] = {k: p[k] for k in FIELDS}
        else:
            log['removed'].append((e, p['name'], p['oblast'], p['obshtina']))

    # The two villages called Вълчовци (Елена) had their attributes swapped; the Елена phone code
    # belongs to 12629, which is administered from Елена.
    a, b = out['Велико Търново']['Елена']['12615'], out['Велико Търново']['Елена']['12629']
    if (a['phone_code'], b['phone_code']) == ('06151', ''):
        a['phone_code'], b['phone_code'] = '', '06151'
        log['phone_code'].append(('12615/12629', 'Вълчовци', '06151 moved to 12629'))

    res = {o: {m: dict(sorted(out[o][m].items(), key=lambda kv: (kv[1]['name'], int(kv[0].split('.')[0]))))
               for m in sorted(out[o])} for o in sorted(out)}
    return res, log


def main():
    utf8_console()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = args[0] if args else DATA_FILE
    dst = args[1] if len(args) > 1 else src
    res, log = build(src)
    text = json.dumps(res, ensure_ascii=False, indent=2) + '\n'
    old = open(src, encoding='utf-8').read()
    os.makedirs(DL, exist_ok=True)
    with open(os.path.join(DL, 'changelog.json'), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print('Changes compared with', os.path.relpath(src))
    for k in ('removed', 'added', 'name', 'type', 'moved', 'town_hall', 'coords', 'post_codes',
              'postcode_econt_override', 'phone_code'):
        print(f'  {k:24} {len(log.get(k, []))}')
    print('  details: downloads/changelog.json')
    if '--check' in sys.argv:
        print('\nNo differences.' if text == old else '\nThe file differs from a fresh build.')
        sys.exit(0 if text == old else 1)
    with open(dst, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('Written', os.path.relpath(dst))


if __name__ == '__main__':
    main()
