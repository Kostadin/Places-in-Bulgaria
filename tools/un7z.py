"""Minimal pure-stdlib 7z extractor (LZMA / LZMA2 / copy coders, single-coder folders).
Used by download.py to unpack the NSI spatial data, so that no 7-Zip installation is needed.
Usage: python3 tools/un7z.py archive.7z outdir
"""
import lzma, os, struct, sys, zlib

class R:
    def __init__(s, b): s.b, s.p = b, 0
    def byte(s):
        v = s.b[s.p]; s.p += 1; return v
    def bytes(s, n):
        v = s.b[s.p:s.p + n]; s.p += n; return v
    def num(s):
        first = s.byte(); mask = 0x80; val = 0
        for i in range(8):
            if first & mask == 0:
                hi = first & (mask - 1)
                return val | (hi << (8 * i))
            val |= s.byte() << (8 * i); mask >>= 1
        return val
    def u32(s): return struct.unpack('<I', s.bytes(4))[0]
    def u64(s): return struct.unpack('<Q', s.bytes(8))[0]
    def bits(s, n):
        out = []; mask = 0; b = 0
        for _ in range(n):
            if mask == 0: b = s.byte(); mask = 0x80
            out.append(bool(b & mask)); mask >>= 1
        return out
    def defined(s, n):
        alldef = s.byte()
        return [True] * n if alldef else s.bits(n)

def read_pack_info(r):
    pack_pos = r.num(); n = r.num(); sizes = []
    while True:
        t = r.byte()
        if t == 0x00: break
        if t == 0x09: sizes = [r.num() for _ in range(n)]
        elif t == 0x0A:
            d = r.defined(n); [r.u32() for x in d if x]
        else: raise ValueError('pack prop %x' % t)
    return pack_pos, sizes

def read_folder(r):
    ncoders = r.num(); coders = []; tot_out = 0
    for _ in range(ncoders):
        flag = r.byte(); idsize = flag & 0xF; cid = r.bytes(idsize)
        if flag & 0x10: nin, nout = r.num(), r.num()
        else: nin, nout = 1, 1
        props = r.bytes(r.num()) if flag & 0x20 else b''
        coders.append((cid, props)); tot_out += nout
    for _ in range(tot_out - 1): r.num(); r.num()  # bind pairs
    return {'coders': coders, 'nout': tot_out}

def read_unpack_info(r):
    assert r.byte() == 0x0B
    n = r.num(); assert r.byte() == 0  # external
    folders = [read_folder(r) for _ in range(n)]
    assert r.byte() == 0x0C
    for f in folders: f['sizes'] = [r.num() for _ in range(f['nout'])]
    t = r.byte()
    if t == 0x0A:
        d = r.defined(n); [r.u32() for x in d if x]; t = r.byte()
    assert t == 0
    return folders

def read_substreams(r, folders):
    nums = [1] * len(folders); sizes = []; t = r.byte()
    if t == 0x0D: nums = [r.num() for _ in folders]; t = r.byte()
    for f, k in zip(folders, nums):
        if k == 0: continue
        total = f['sizes'][-1]; acc = 0; part = []
        if t == 0x09:
            for _ in range(k - 1): v = r.num(); part.append(v); acc += v
        part.append(total - acc); sizes.append(part)
    if t == 0x09: t = r.byte()
    while t != 0:
        if t == 0x0A:
            cnt = sum(nums); d = r.defined(cnt); [r.u32() for x in d if x]
        t = r.byte()
    return nums, sizes

def read_streams_info(r):
    pack = folders = None; sub = None
    while True:
        t = r.byte()
        if t == 0: break
        if t == 0x06: pack = read_pack_info(r)
        elif t == 0x07: folders = read_unpack_info(r)
        elif t == 0x08: sub = read_substreams(r, folders)
        else: raise ValueError('streams prop %x' % t)
    return pack, folders, sub

def decode_folder(data, folder):
    assert len(folder['coders']) == 1, 'multi-coder folders unsupported'
    cid, props = folder['coders'][0]
    if cid == b'\x00': return data
    if cid == b'\x21':
        filt = lzma._decode_filter_properties(lzma.FILTER_LZMA2, props)
    elif cid == b'\x03\x01\x01':
        filt = lzma._decode_filter_properties(lzma.FILTER_LZMA1, props)
    else: raise ValueError('coder %r unsupported' % cid)
    d = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[filt])
    return d.decompress(data, max_length=folder['sizes'][-1])

def unpack_folders(buf, base, pack, folders):
    pos = base + pack[0]; out = []
    for f, sz in zip(folders, pack[1]):
        out.append(decode_folder(buf[pos:pos + sz], f)); pos += sz
    return out

def main(path, outdir):
    buf = open(path, 'rb').read()
    assert buf[:6] == b"7z\xbc\xaf'\x1c"
    nho, nhs = struct.unpack('<QQ', buf[12:28])
    base = 32; hdr = buf[base + nho: base + nho + nhs]
    r = R(hdr); t = r.byte()
    while t == 0x17:  # encoded header
        pack, folders, _ = read_streams_info(r)
        hdr = unpack_folders(buf, base, pack, folders)[0]; r = R(hdr); t = r.byte()
    assert t == 0x01
    t = r.byte()
    if t == 0x02:  # archive props
        while r.byte() != 0: pass
        t = r.byte()
    pack = folders = sub = None
    if t == 0x03: t = r.byte()  # additional streams (unused)
    if t == 0x04:
        pack, folders, sub = read_streams_info(r); t = r.byte()
    names = []; empty = []
    if t == 0x05:
        nfiles = r.num(); empty = [False] * nfiles
        while True:
            pt = r.byte()
            if pt == 0: break
            size = r.num(); body = R(r.bytes(size))
            if pt == 0x0E: empty = body.bits(nfiles)
            elif pt == 0x11:
                assert body.byte() == 0
                raw = body.b[body.p:].decode('utf-16-le')
                names = raw.split('\x00')[:nfiles]
    datas = unpack_folders(buf, base, pack, folders) if folders else []
    streams = []
    nums, sizes = sub if sub else ([1] * len(folders), [[f['sizes'][-1]] for f in folders])
    for d, part in zip([d for d, k in zip(datas, nums) if k], sizes):
        p = 0
        for s in part: streams.append(d[p:p + s]); p += s
    si = 0
    for name, e in zip(names, empty):
        dst = os.path.join(outdir, name.replace('\\', '/'))
        if '..' in dst.split('/'): raise ValueError('bad path')
        if e:
            os.makedirs(dst, exist_ok=True); continue
        os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        open(dst, 'wb').write(streams[si]); print(name, len(streams[si])); si += 1

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
