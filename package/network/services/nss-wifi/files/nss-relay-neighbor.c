// SPDX-License-Identifier: GPL-2.0-only
/* Send one ordinary unicast ARP request using the STA's current on-link gateway. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <limits.h>
#include <linux/if_ether.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <net/if_arp.h>
#include <net/route.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

enum { SKIP = 2, FRAME_SIZE = ETH_ZLEN };

static bool valid_interface(const char *name)
{
	size_t length = strnlen(name, IFNAMSIZ);
	if (!length || length == IFNAMSIZ)
		return false;
	for (size_t i = 0; i < length; i++)
		if (!((name[i] >= 'a' && name[i] <= 'z') ||
		      (name[i] >= 'A' && name[i] <= 'Z') ||
		      (name[i] >= '0' && name[i] <= '9') ||
		      name[i] == '_' || name[i] == '-' || name[i] == '.'))
			return false;
	return true;
}

static bool valid_mac(const unsigned char mac[ETH_ALEN])
{
	unsigned char nonzero = 0;
	for (size_t i = 0; i < ETH_ALEN; i++)
		nonzero |= mac[i];
	return nonzero && !(mac[0] & 1);
}

static bool parse_mac(const char *text, unsigned char mac[ETH_ALEN])
{
	unsigned octets[ETH_ALEN];
	int end = 0;
	if (strlen(text) != 17)
		return false;
	for (size_t i = 0; i < 17; i++) {
		if (i % 3 == 2) {
			if (text[i] != ':')
				return false;
		} else if (!((text[i] >= '0' && text[i] <= '9') ||
			     (text[i] >= 'a' && text[i] <= 'f') ||
			     (text[i] >= 'A' && text[i] <= 'F'))) {
			return false;
		}
	}
	if (sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x%n", &octets[0], &octets[1],
		   &octets[2], &octets[3], &octets[4], &octets[5], &end) != 6 || end != 17)
		return false;
	for (size_t i = 0; i < ETH_ALEN; i++)
		mac[i] = octets[i];
	return valid_mac(mac);
}

static bool read_gateway(FILE *table, const char *name, struct in_addr *gateway)
{
	char line[512], device[IFNAMSIZ];
	unsigned long destination, next_hop, metric, mask, best = ULONG_MAX;
	unsigned flags;
	bool found = false;
	while (fgets(line, sizeof(line), table)) {
		if (sscanf(line, "%15s %lx %lx %x %*u %*u %lu %lx", device,
			   &destination, &next_hop, &flags, &metric, &mask) != 6 ||
		    strcmp(device, name) || destination || mask || !next_hop ||
		    next_hop > UINT32_MAX || (flags & (RTF_UP | RTF_GATEWAY)) !=
			(RTF_UP | RTF_GATEWAY) || (flags & RTF_REJECT) || metric > best)
			continue;
		/* /proc/net/route prints the native value of a network-order address. */
		gateway->s_addr = (uint32_t)next_hop;
		best = metric;
		found = true;
	}
	return found;
}

static bool read_neighbor(FILE *table, const char *name, struct in_addr gateway,
			  unsigned char mac[ETH_ALEN])
{
	char line[512], address[64], hardware[64], mask[64], device[IFNAMSIZ];
	unsigned type, flags;
	struct in_addr parsed;
	while (fgets(line, sizeof(line), table))
		if (sscanf(line, "%63s %x %x %63s %63s %15s", address, &type,
			   &flags, hardware, mask, device) == 6 &&
		    !strcmp(device, name) && type == ARPHRD_ETHER && (flags & ATF_COM) &&
		    inet_pton(AF_INET, address, &parsed) == 1 &&
		    parsed.s_addr == gateway.s_addr && parse_mac(hardware, mac))
			return true;
	return false;
}

static void build_request(unsigned char frame[FRAME_SIZE], const unsigned char own[ETH_ALEN],
			  const unsigned char target[ETH_ALEN], struct in_addr address,
			  struct in_addr gateway)
{
	memset(frame, 0, FRAME_SIZE);
	memcpy(frame, target, ETH_ALEN);
	memcpy(frame + ETH_ALEN, own, ETH_ALEN);
	frame[12] = 0x08; frame[13] = 0x06; /* Ethernet ARP */
	frame[15] = 1; /* Ethernet hardware type */
	frame[16] = 0x08; /* IPv4 protocol type */
	frame[18] = ETH_ALEN; frame[19] = 4;
	frame[21] = ARPOP_REQUEST;
	memcpy(frame + 22, own, ETH_ALEN);
	memcpy(frame + 28, &address.s_addr, 4);
	/* Target hardware address remains zero in this ARP request. */
	memcpy(frame + 38, &gateway.s_addr, 4);
}

int main(int argc, char **argv)
{
	if (argc != 2 || !valid_interface(argv[1]))
		return SKIP;
	const char *name = argv[1];
	struct in_addr gateway = {0}, address = {0}, mask = {0};
	unsigned char own[ETH_ALEN], target[ETH_ALEN], frame[FRAME_SIZE];
	FILE *table = fopen("/proc/net/route", "r");
	if (!table)
		return SKIP;
	bool found = read_gateway(table, name, &gateway);
	fclose(table);
	if (!found)
		return SKIP;
	table = fopen("/proc/net/arp", "r");
	if (!table)
		return SKIP;
	found = read_neighbor(table, name, gateway, target);
	fclose(table);
	if (!found)
		return SKIP;
	int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
	if (fd < 0)
		return 1;
	struct ifreq interface = {0};
	memcpy(interface.ifr_name, name, strlen(name) + 1);
	unsigned index = if_nametoindex(name);
	if (!index || ioctl(fd, SIOCGIFFLAGS, &interface) || !(interface.ifr_flags & IFF_UP))
		goto skip;
	if (ioctl(fd, SIOCGIFHWADDR, &interface) || interface.ifr_hwaddr.sa_family != ARPHRD_ETHER)
		goto skip;
	memcpy(own, interface.ifr_hwaddr.sa_data, ETH_ALEN);
	if (!valid_mac(own) || ioctl(fd, SIOCGIFADDR, &interface))
		goto skip;
	address = ((struct sockaddr_in *)&interface.ifr_addr)->sin_addr;
	if (ioctl(fd, SIOCGIFNETMASK, &interface))
		goto skip;
	mask = ((struct sockaddr_in *)&interface.ifr_netmask)->sin_addr;
	if (!address.s_addr || !mask.s_addr || address.s_addr == gateway.s_addr ||
	    ((address.s_addr ^ gateway.s_addr) & mask.s_addr) || if_nametoindex(name) != index)
		goto skip;
	close(fd);
	build_request(frame, own, target, address, gateway);
	fd = socket(AF_PACKET, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, htons(ETH_P_ARP));
	if (fd < 0)
		return 1;
	struct sockaddr_ll destination = {
		.sll_family = AF_PACKET, .sll_protocol = htons(ETH_P_ARP),
		.sll_ifindex = index, .sll_halen = ETH_ALEN
	};
	memcpy(destination.sll_addr, target, ETH_ALEN);
	ssize_t sent = sendto(fd, frame, sizeof(frame), 0,
			     (struct sockaddr *)&destination, sizeof(destination));
	close(fd);
	return sent == (ssize_t)sizeof(frame) ? 0 : 1;
skip:
	close(fd);
	return SKIP;
}
