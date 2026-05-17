"""将 ICO 文件注入到 exe 资源段。
解决 PyInstaller --icon 在部分环境不生效的问题。
"""
import sys
import struct
import win32api


def inject_icon(exe_path, ico_path):
    with open(ico_path, 'rb') as f:
        ico_data = f.read()

    reserved, typ, count = struct.unpack_from('<HHH', ico_data, 0)
    if reserved != 0 or typ != 1:
        raise ValueError("Invalid ICO file")

    entries = []
    for i in range(count):
        off = 6 + i * 16
        bW, bH, bCol, bRsv, wPlanes, wBits, dwSize, dwOff = (
            struct.unpack_from('<BBBBHHIH', ico_data, off))
        w = 256 if bW == 0 else bW
        h = 256 if bH == 0 else bH
        entries.append({
            'w': w, 'h': h, 'colors': bCol,
            'planes': wPlanes, 'bits': wBits, 'size': dwSize,
            'data': ico_data[dwOff:dwOff + dwSize]
        })

    # RT_GROUP_ICON directory
    grp_header = struct.pack('<HHH', 0, 1, count)
    grp_entries = b''
    for idx, e in enumerate(entries):
        wb = 0 if e['w'] >= 256 else e['w']
        hb = 0 if e['h'] >= 256 else e['h']
        grp_entries += struct.pack('<BBBBHHIH',
            wb, hb, e['colors'], 0, e['planes'], e['bits'], e['size'], idx + 1)
    grp_icon_data = grp_header + grp_entries

    h = win32api.BeginUpdateResource(exe_path, False)
    try:
        for idx, e in enumerate(entries):
            win32api.UpdateResource(h, 3, idx + 1, e['data'])  # RT_ICON
            print(f"  RT_ICON {idx + 1}: {e['w']}x{e['h']}, {e['size']} bytes")

        win32api.UpdateResource(h, 14, 1, grp_icon_data)  # RT_GROUP_ICON
        print(f"  RT_GROUP_ICON: {len(grp_icon_data)} bytes")

        win32api.EndUpdateResource(h, False)
        print(f"OK: Icon injected into {exe_path}")
    except Exception:
        win32api.EndUpdateResource(h, True)
        raise


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: python fix_icon.py <exe_path> <ico_path>")
        sys.exit(1)
    inject_icon(sys.argv[1], sys.argv[2])
