"""Turns the CRC postcode index into {EKATTE code: set of postcodes}.

Part 1 of the index has one row per settlement (code, name, municipality, oblast).
Each row is matched to an EKATTE code in this order:
  1. same oblast + same name, if the name is unique in the oblast;
  2. ...plus the same municipality;
  3. a close spelling (similarity >= 0.8) inside the same municipality;
  4. MANUAL below, for rows the index lists under a former name or as a separate
     village that has since been merged into a town.

Part 2 lists streets of the larger towns, each with its own postcode. A code is
given to a town when most of its street rows name that town, the town is in the
same oblast, and the code is in the same postal district (first digit for Sofia,
first two digits elsewhere) as the town's base code.
"""
import collections
import difflib

from common import load_crc

# Rows the automatic matching cannot place. Each one is documented in the EKATTE change log (Ekat_ver.txt).
MANUAL = {
    ('8125', 'Банево'): '07079', ('8127', 'Ветрен'): '07079', ('8112', 'Рудник'): '07079',  # merged into Бургас
    ('8115', 'Мина Черно море'): '07079', ('8124', 'Бургаски мин. бани'): '07079',        # parts of Бургас
    ('8215', 'Каменар'): '57491',                                                            # merged into Поморие (ДВ 53/2022)
    ('2270', 'Бов'): '04546', ('2271', 'Гара Бов'): '14461', ('2273', 'Лакатник'): '43092', ('2272', 'Гара Лакатник'): '14475',
    ('3945', 'Орешец'): '53758', ('3940', 'Гара Орешец'): '14489', ('9780', 'Гара Хитрино'): '14516',
    ('2100', 'Елин Пелин'): '27303', ('2109', 'Гара Елин Пелин'): '18490', ('8432', 'Гара Завет'): '30051',
    ('9930', 'Каспичан'): '36587', ('9931', 'Каспичан село'): '36590', ('2030', 'Костенец'): '38902', ('2042', 'Костенец село'): '38916',
    ('5041', 'Гашевци'): '14578', ('1186', 'Герман'): '14831', ('6219', 'Горно Белево'): '16691', ('1807', 'Желява'): '29204',
    ('5192', 'Стефан Стамболово'): '17467', ('2920', 'Мусомища'): '49432', ('4727', 'Орешица'): '53792', ('6000', 'Стара'): '68850',
    ('5081', 'Вълчовци'): '12629', ('5086', 'Вълчовци'): '12615',
    ('8604', 'Гара Ямбол'): '87374', ('4410', 'Гара Пазарджик'): '55155', ('7737', 'Гара Търговище'): '73626', ('7101', 'Гара Бяла'): '07603',
}
# Resort complexes have their own postcodes but no EKATTE code; they are kept as separate к.к. entries.
RESORTS = {'9620': 'Албена', '2010': 'Боровец', '9007': 'Златни пясъци', '9130': 'Камчия', '4870': 'Пампорово',
           '9695': 'Русалка', '9006': 'Свети Константин и Елена', '8240': 'Слънчев бряг'}
SOFIA_CITY = '68134'


def norm(s):
    return s.lower().replace('-', ' ').replace('ё', 'е').strip()


def build_postcode_map(atte, obl):
    """Returns (codes, unplaced, conflicts)."""
    def pobl(r):  # the index uses "София" for both the capital and the surrounding oblast
        return 'София' if r['oblast'] in ('SOF', 'SFO') else obl[r['oblast']]['name']

    def nmuni(m):
        m = m.strip()
        if m.lower().startswith('район'):
            return 'столична'
        return norm({'Бобовдол': 'Бобов дол'}.get(m, m))

    def same_muni(r, mm):
        return norm(r['obshtina_name']) == mm or (mm == 'добрич' and r['obshtina_name'] == 'Добрич-селска')

    by_on = collections.defaultdict(list)
    for e, r in atte.items():
        by_on[(pobl(r), norm(r['name']))].append(e)

    def match(name, muni, oblc):
        c = by_on.get((oblc, norm(name)), [])
        if len(c) == 1:
            return c[0]
        mm = nmuni(muni)
        c2 = [e for e in c if same_muni(atte[e], mm)]
        if len(c2) == 1:
            return c2[0]
        pool = [e for e, r in atte.items() if pobl(r) == oblc and same_muni(r, mm)]
        best = sorted(((difflib.SequenceMatcher(None, norm(name), norm(atte[e]['name'])).ratio(), e) for e in pool), reverse=True)
        if best and best[0][0] >= 0.8 and (len(best) == 1 or best[1][0] < best[0][0]):
            return best[0][1]
        return None

    sec1, sec2 = load_crc()
    codes = collections.defaultdict(set)
    unplaced = []
    sec1_name = collections.defaultdict(set)
    for code, name, muni, oblc in sec1:
        e = MANUAL.get((code, name)) or match(name, muni, oblc)
        if e:
            codes[e].add(code)
            sec1_name[norm(name)].add(e)
        elif code not in RESORTS:
            unplaced.append((code, name, muni, oblc))
    sec1_name['стара загора'] = {'68850'}  # part 1 lists Стара Загора as "Стара"

    base = {}
    for e, cs in codes.items():
        for c in cs:
            base.setdefault(c, set()).add(e)

    def district(c):
        return c[:1] if c[0] == '1' else c[:2]

    votes = collections.defaultdict(collections.Counter)
    for (o, name), cs in sec2.items():
        n = norm(name)
        cand = sec1_name.get(n, set())
        same = {e for e in cand if pobl(atte[e]) == o}
        if n in ('банево', 'ветрен'):
            same = {'07079'}
        if same:
            cand = same
        elif o == 'София':  # street rows of Sofia quarters that are not settlements
            cand = {SOFIA_CITY}
        for c, k in cs.items():
            ok = {e for e in cand if any(district(b) == district(c) for b in codes[e])}
            if len(ok) == 1:
                votes[c][next(iter(ok))] += k
    conflicts = []
    for c, v in votes.items():
        (e, k), *rest = v.most_common()
        if rest and rest[0][1] * 5 > k:  # no clear (5:1) majority: leave the code out
            conflicts.append((c, dict(v)))
            continue
        if c in base and e not in base[c]:
            conflicts.append((c, 'base code of another place', e, sorted(base[c])))
        codes[e].add(c)
    return codes, unplaced, conflicts
