#!/usr/bin/env python3
"""Check ARP wire format and reject invalid route/neighbor data without network access."""
from pathlib import Path
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[2]
source = repo / 'package/network/services/nss-wifi/files/nss-relay-neighbor.c'
harness = r'''
#define _GNU_SOURCE
#define main neighbor_program_main
#include "SOURCE_PATH"
#undef main
#include <assert.h>

static FILE *fixture(const char *text) {
    FILE *file = tmpfile(); assert(file);
    assert(fputs(text, file) >= 0); rewind(file); return file;
}

int main(void) {
    assert(valid_interface("phy1-sta0"));
    assert(!valid_interface(""));
    assert(!valid_interface("1234567890123456"));
    assert(!valid_interface("bad/name"));
    assert(!valid_interface("sta\nother"));
    unsigned char mac[6];
    assert(parse_mac("02:11:22:33:44:55", mac));
    assert(!parse_mac("00:00:00:00:00:00", mac));
    assert(!parse_mac("ff:ff:ff:ff:ff:ff", mac));
    assert(!parse_mac("01:11:22:33:44:55", mac));
    assert(!parse_mac("02:11:22:33:4 :55", mac));
    assert(!parse_mac("02:11:22:33:44:5z", mac));
    assert(!parse_mac("02:11:22:33:44:555", mac));

    char routes[1024];
    snprintf(routes, sizeof(routes),
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "eth1 00000000 %08x 0003 0 0 0 00000000 0 0 0\n"
        "phy1-sta0 00000000 %08x 0003 0 0 20 00000000 0 0 0\n"
        "phy1-sta0 00000000 %08x 0203 0 0 0 00000000 0 0 0\n"
        "phy1-sta0 00000000 %08x 0003 0 0 10 00000000 0 0 0\n",
        inet_addr("198.51.100.1"), inet_addr("192.0.2.1"),
        inet_addr("192.0.2.253"), inet_addr("192.0.2.254"));
    struct in_addr gateway = {0};
    FILE *file = fixture(routes);
    assert(read_gateway(file, "phy1-sta0", &gateway)); fclose(file);
    assert(gateway.s_addr == inet_addr("192.0.2.254"));
    file = fixture("phy1-sta0 00000000 00000000 0001 0 0 0 00000000\n");
    assert(!read_gateway(file, "phy1-sta0", &gateway)); fclose(file);

    file = fixture(
        "IP address HW type Flags HW address Mask Device\n"
        "192.0.2.254 0x1 0x2 02:11:22:33:44:55 * eth1\n"
        "192.0.2.254 0x1 0x0 02:11:22:33:44:55 * phy1-sta0\n"
        "192.0.2.254 0x1 0x2 01:11:22:33:44:55 * phy1-sta0\n"
        "192.0.2.254 0x1 0x2 02:11:22:33:44:55 * phy1-sta0\n");
    assert(read_neighbor(file, "phy1-sta0", gateway, mac)); fclose(file);
    const unsigned char target[6] = {2, 0x11, 0x22, 0x33, 0x44, 0x55};
    assert(!memcmp(mac, target, 6));
    file = fixture("192.0.2.254 0x1 0x0 02:11:22:33:44:55 * phy1-sta0\n");
    assert(!read_neighbor(file, "phy1-sta0", gateway, mac)); fclose(file);

    const unsigned char own[6] = {2, 0xaa, 0xbb, 0xcc, 0xdd, 0xee};
    unsigned char frame[FRAME_SIZE];
    struct in_addr address = {.s_addr = inet_addr("192.0.2.2")};
    build_request(frame, own, target, address, gateway);
    const unsigned char expected[] =
        "\x02\x11\x22\x33\x44\x55\x02\xaa\xbb\xcc\xdd\xee\x08\x06"
        "\x00\x01\x08\x00\x06\x04\x00\x01\x02\xaa\xbb\xcc\xdd\xee"
        "\xc0\x00\x02\x02\x00\x00\x00\x00\x00\x00\xc0\x00\x02\xfe";
    assert(sizeof(expected) - 1 == 42 && FRAME_SIZE == 60);
    assert(!memcmp(frame, expected, 42));
    for (size_t i = 42; i < sizeof(frame); i++) assert(!frame[i]);
    char *bad[] = {"neighbor", "bad/name"};
    assert(neighbor_program_main(2, bad) == SKIP);
    puts("ARP frame, route selection, neighbor validation and interface bounds passed");
    return 0;
}
'''.replace('SOURCE_PATH', str(source).replace('\\', '\\\\').replace('"', '\\"'))

with tempfile.TemporaryDirectory(prefix='nss-neighbor-test-') as temporary:
    directory = Path(temporary)
    test = directory / 'test.c'
    binary = directory / 'test'
    test.write_text(harness)
    subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fno-omit-frame-pointer', '-fsanitize=address,undefined', '-no-pie',
                    '-o', str(binary), str(test)], check=True)
    subprocess.run([str(binary)], check=True)
