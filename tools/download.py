"""Downloads every reference source into ./downloads (about 30 MB).

Usage:  python3 tools/download.py [--force]

  --force   download again even if a file is already present

Only the Python standard library is used. Ghostscript is needed for one step
only: turning the CRC postcode PDF into text. Without it the postcode checks
are skipped (verify.py) or refused (build.py).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DL, utf8_console  # noqa: E402
import un7z  # noqa: E402

UA = {'User-Agent': 'Places-in-Bulgaria-verifier/1.0 (+https://github.com/Kostadin/Places-in-Bulgaria)'}
FORCE = '--force' in sys.argv

# SHA-256 of the files the current Places-in-Bulgaria.json was built from.
# A mismatch means the publisher has released a newer version since then.
SNAPSHOT = {
    'ekatte/Ekatte-2025-json.zip': '0bf017c6b3bd5683215f9734cc5bb70c15c3b96b2fd9b6dda5d5096e92bae397',
    'spatial/SU_BG_NSI_NM_2025_1.7z': '62962a44d1242a6cfffc9f787429772cdff8ada864a6bf295dc5c3b687b7fd52',
    'spatial/SU_BG_NSI_LAU_2024_1.7z': '62014ce0c1cc167baf6997c00191bfabf3ae76c2df2767ec1db3079f3c7170e8',
    'post/crc2016.pdf': '4444af53edfaa06cb76daace512b3826b889f8d70e3b4407efd1d86474071138',
}

EKATTE_URL = 'https://www.nsi.bg/nrnm/ekatte/archive/json/Ekatte-2025-json.zip/download'
SPATIAL_URL = 'https://www.nsi.bg/nrnm/download/{}/spatial-data-files'
CRC_URL = 'https://www.crc.bg/files/_bg/post_codes_all__4_-_2016full.pdf'
ECONT_URL = 'https://ee.econt.com/services/Nomenclatures/NomenclaturesService.getCities.json'
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.private.coffee/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
# every OSM place node inside Bulgaria's bounding box that carries an EKATTE code
OVERPASS_Q = '[out:json][timeout:300];node["place"]["ekatte"](41.2,22.3,44.25,28.65);out body;'


def path(*p):
    full = os.path.join(DL, *p)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def fetch(url, dst, data=None, headers=None, timeout=300):
    if os.path.exists(dst) and os.path.getsize(dst) > 0 and not FORCE:
        print(f'  already present: {os.path.relpath(dst, DL)}')
        return dst
    print(f'  downloading {url}')
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dst + '.part', 'wb') as f:
        shutil.copyfileobj(r, f)
    os.replace(dst + '.part', dst)
    return dst


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def nsi_spatial():
    """The NSI download page numbers its files; find the settlement points and municipality borders by name."""
    found = {}
    for i in range(1, 16):
        try:
            req = urllib.request.Request(SPATIAL_URL.format(i), method='HEAD', headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                m = re.search(r'filename="?([^";]+)', r.headers.get('Content-Disposition', ''))
        except Exception:
            continue
        if m:
            name = m.group(1)
            for kind in ('NM', 'LAU'):
                if name.startswith(f'SU_BG_NSI_{kind}_') and name.endswith('.7z'):
                    found[kind] = max(found.get(kind, ('', 0)), (name, i))
    for kind, what in (('NM', 'settlement points'), ('LAU', 'municipality borders')):
        if kind not in found:
            sys.exit(f'Could not find the NSI {what} on {SPATIAL_URL.format("N")}')
        name, i = found[kind]
        print(f'NSI {what}: {name}')
        dst = fetch(SPATIAL_URL.format(i), path('spatial', name))
        un7z.main(dst, path('spatial', 'x'))
        # keep only the .gpkg at a predictable place
        for f in os.listdir(path('spatial', 'x')):
            if f.endswith('.gpkg'):
                os.replace(path('spatial', 'x', f), path('spatial', f))


def ghostscript():
    for exe in ('gs', 'gswin64c', 'gswin32c'):
        p = shutil.which(exe)
        if p:
            return p
    if os.name == 'nt':  # the Windows installer does not add itself to PATH
        hits = sorted(__import__('glob').glob(r'C:\Program Files\gs\gs*\bin\gswin64c.exe'))
        if hits:
            return hits[-1]
    return None


def main():
    utf8_console()
    os.makedirs(DL, exist_ok=True)

    print('NSI EKATTE register (names, types, municipalities, kmetstva)')
    z = fetch(EKATTE_URL, path('ekatte', 'Ekatte-2025-json.zip'))
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            if n.endswith(('.json', '.txt')) and '/' not in n and '..' not in n:
                with open(path('ekatte', n), 'wb') as f:
                    f.write(zf.read(n))

    nsi_spatial()

    print('CRC postcode index')
    pdf = fetch(CRC_URL, path('post', 'crc2016.pdf'))
    txt = path('post', 'crc2016.txt')
    if not os.path.exists(txt) or FORCE:
        gs = ghostscript()
        if gs:
            print('  converting PDF to text with Ghostscript (takes a minute)')
            subprocess.run([gs, '-q', '-dNOPAUSE', '-dBATCH', '-dSAFER', '-sDEVICE=txtwrite',
                            '-sOutputFile=' + txt, pdf], check=True)
        else:
            print('  WARNING: Ghostscript not found, so the postcode PDF cannot be read.\n'
                  '  Install it (see README) and run this script again. Postcode checks will be skipped.')

    print('Econt city list (live)')
    fetch(ECONT_URL, path('econt', 'cities.json'), data=json.dumps({'countryCode': 'BGR'}).encode(),
          headers={'Content-Type': 'application/json'})

    print('OpenStreetMap places with EKATTE tags (live, may take a few minutes)')
    dst = path('osm', 'osm_places.json')
    body = urllib.parse.urlencode({'data': OVERPASS_Q}).encode()
    for url in OVERPASS * 2:  # the public servers are often busy; try each twice
        try:
            fetch(url, dst, data=body, timeout=600)
            json.load(open(dst, encoding='utf-8'))
            break
        except Exception as ex:
            print(f'  {url} failed: {ex}')
            if os.path.exists(dst):
                os.remove(dst)
    else:
        sys.exit('All Overpass servers failed; try again later.')

    print('\nSHA-256 of the downloaded files compared with the ones the data was built from:')
    for rel, want in SNAPSHOT.items():
        p = os.path.join(DL, rel)
        if not os.path.exists(p):
            print(f'  {rel}: not downloaded (a newer version is probably published)')
            continue
        got = sha256(p)
        print(f'  {rel}: {"same" if got == want else "DIFFERENT (" + got[:16] + "...) - the source has been updated"}')
    print('  econt/cities.json, osm/osm_places.json: live data, changes every day')
    print('\nDone. Next:  python3 tools/verify.py')


if __name__ == '__main__':
    main()
