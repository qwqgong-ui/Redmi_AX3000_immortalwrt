// SPDX-License-Identifier: GPL-2.0-only
/*
 * NSS ownership for QCA tag_8021q DSA ports.
 * Topology collection is based on kuncy7/openwrt-nss-edma,
 * bb783538744ff9f2b924da8af8288eab409d5cf1. Control publication and
 * teardown are coordinated with the current driver/bridge/ECM APIs.
 */
#include <linux/module.h>
#include <linux/netdevice.h>
#include <linux/etherdevice.h>
#include <linux/if_vlan.h>
#include <linux/if_bridge.h>
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/workqueue.h>
#include <linux/rtnetlink.h>
#include <linux/dsa/8021q.h>
#include <linux/delay.h>
#include <net/dsa.h>
#include <net/switchdev.h>
#include <nss_api_if.h>

struct net_device *dsa_tag_8021q_find_user(struct net_device *conduit,
	int source_port, int switch_id, int vid, int vbid);
int nss_bridge_mgr_offload_port_join(struct net_device *dev);
int nss_bridge_mgr_offload_port_revoke(struct net_device *dev, int ifnum);
extern void ecm_notifier_offload_pause(bool pause);
extern bool ecm_notifier_offload_drained(void);

#define DSA_NSS_MAX_NODES 32
#define DSA_NSS_MAX_CONDUITS 4

enum dsa_nss_phase { DSA_NSS_FREE, DSA_NSS_CONFIGURING, DSA_NSS_READY,
	DSA_NSS_REVOKING, DSA_NSS_UNKNOWN };
struct dsa_nss_node {
	struct net_device *dev;
	u16 vid;
	int phys_if, ifnum;
	unsigned int mtu;
	u8 mac[ETH_ALEN];
	enum dsa_nss_phase phase;
	bool handler, published;
};
struct dsa_nss_conduit {
	struct net_device *dev;
	bool held;
};
struct dsa_nss_want {
	struct net_device *dev, *conduit;
	u16 vid;
};

static struct dsa_nss_node nodes[DSA_NSS_MAX_NODES];
static struct dsa_nss_conduit conduits[DSA_NSS_MAX_CONDUITS];
static DEFINE_MUTEX(owner_lock);
static DEFINE_SPINLOCK(table_lock);
static struct delayed_work reconcile_work;
static struct dentry *dentry;
static bool enabled, initialised, stopping, pinned, ready;
static bool allocation_uncertain, paused;
static void (*pause_fn)(bool);
static bool (*drained_fn)(void);
static int last_error;

static void owner_pin(void)
{
	if (!pinned) {
		__module_get(THIS_MODULE);
		pinned = true;
	}
}

static bool owner_has_resources(void)
{
	int i;

	if (allocation_uncertain)
		return true;
	for (i = 0; i < DSA_NSS_MAX_NODES; i++)
		if (nodes[i].ifnum >= 0)
			return true;
	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++)
		if (conduits[i].held)
			return true;
	return paused;
}

static void owner_unpin_if_empty(void)
{
	if (pinned && !owner_has_resources()) {
		pinned = false;
		module_put(THIS_MODULE);
	}
}

/* Preserve the administrator's frontend flags; keep the provider referenced
 * until the pause is balanced. No provider exists during initial S94 setup.
 */
static int rules_provider_hold(void)
{
	if (!pause_fn) {
		pause_fn = symbol_get(ecm_notifier_offload_pause);
		drained_fn = symbol_get(ecm_notifier_offload_drained);
		if (!pause_fn && !drained_fn)
			return 0;
		if (!pause_fn || !drained_fn) {
			if (pause_fn)
				symbol_put(ecm_notifier_offload_pause);
			if (drained_fn)
				symbol_put(ecm_notifier_offload_drained);
			pause_fn = NULL;
			drained_fn = NULL;
			return -EOPNOTSUPP;
		}
	}
	return 0;
}

static int rules_pause_and_drain(void)
{
	unsigned long deadline;
	int ret;

	if (!paused) {
		ret = rules_provider_hold();
		if (ret || !pause_fn)
			return ret;
		owner_pin();
		pause_fn(true);
		paused = true;
	}
	deadline = jiffies + 5 * HZ;
	do {
		if (drained_fn())
			return 0;
		msleep(20);
	} while (time_before(jiffies, deadline));
	return -ETIMEDOUT;
}

static void rules_resume(void)
{
	if (paused) {
		pause_fn(false);
		paused = false;
	}
	/* READY nodes keep the provider referenced too. Its destroy-unknown
	 * record must not disappear while physical interfaces still depend on it.
	 */
	if (!pause_fn || owner_has_resources())
		return;
	symbol_put(ecm_notifier_offload_drained);
	symbol_put(ecm_notifier_offload_pause);
	pause_fn = NULL;
	drained_fn = NULL;
}

static struct dsa_port *port_of(struct net_device *dev)
{
	struct dsa_port *dp;

	if (!dsa_user_dev_check(dev))
		return NULL;
	dp = dsa_port_from_netdev(dev);
	if (IS_ERR_OR_NULL(dp) || !dp->cpu_dp || !dp->cpu_dp->tag_ops ||
	    dp->cpu_dp->tag_ops->proto != DSA_TAG_PROTO_QCA_8021Q ||
	    !dp->ds->tag_8021q_ctx)
		return NULL;
	return dp;
}

/* This initial data plane is limited to VLAN-unaware bridges. Unsupported
 * topology is refused instead of being assigned a guessed interface number.
 */
static int collect(struct dsa_nss_want *want)
{
	struct net_device *dev;
	int n = 0, i;

	ASSERT_RTNL();
	for_each_netdev(&init_net, dev) {
		struct dsa_port *dp = port_of(dev);
		struct net_device *conduit, *bound;
		struct net_device *upper;
		struct list_head *iter;
		u16 vid;

		if (!dp || !(dev->flags & IFF_UP))
			continue;
		if (dp->bridge && br_vlan_enabled(dsa_port_bridge_dev_get(dp)))
			return -EOPNOTSUPP;
		netdev_for_each_upper_dev_rcu(dev, upper, iter)
			if (is_vlan_dev(upper))
				return -EOPNOTSUPP;
		conduit = dp->cpu_dp->conduit;
		if (!netif_running(conduit))
			return -EAGAIN;
		if (dp->bridge && dp->bridge->tx_fwd_offload) {
			unsigned int vbid = dsa_port_bridge_num_get(dp);

			vid = dsa_tag_8021q_bridge_vid(vbid);
			bound = dsa_tag_8021q_find_user(conduit, -1, -1, vid, vbid);
			if (!bound)
				return -EAGAIN;
		} else {
			vid = dsa_tag_8021q_standalone_vid(dp);
			bound = dev;
		}
		for (i = 0; i < n; i++)
			if (want[i].vid == vid && want[i].conduit == conduit)
				break;
		if (i < n)
			continue;
		if (n == DSA_NSS_MAX_NODES)
			return -ENOSPC;
		want[n++] = (struct dsa_nss_want) { bound, conduit, vid };
	}
	return n;
}

static int conduit_attach(struct net_device *dev)
{
	int i, empty = -1, ret;

	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++) {
		if (conduits[i].dev == dev)
			return nss_data_plane_state(dev) == NSS_DATA_PLANE_READY ? 0 : -EBUSY;
		if (!conduits[i].dev && empty < 0)
			empty = i;
	}
	if (empty < 0)
		return -ENOSPC;
	owner_pin();
	ret = nss_data_plane_attach(dev);
	if (!ret || nss_data_plane_state(dev) != NSS_DATA_PLANE_HOST) {
		dev_hold(dev);
		conduits[empty].dev = dev;
		conduits[empty].held = true;
	}
	return ret;
}

static int node_create(struct dsa_nss_node *n, struct dsa_nss_want *w)
{
	int ret;

	owner_pin();
	n->ifnum = nss_dynamic_interface_alloc_node(NSS_DYNAMIC_INTERFACE_TYPE_VLAN);
	if (n->ifnum < 0) {
		/* Allocation timeout does not identify an orphaned firmware node.
		 * Do not repeat allocations blindly within this boot.
		 */
		allocation_uncertain = true;
		return -EIO;
	}
	n->phase = DSA_NSS_CONFIGURING;
	n->dev = w->dev;
	dev_hold(n->dev);
	n->vid = w->vid;
	n->phys_if = nss_cmn_get_interface_number_by_dev(w->conduit);
	n->mtu = w->dev->mtu;
	ether_addr_copy(n->mac, w->dev->dev_addr);
	if (n->phys_if < 0 || n->phys_if >= NSS_MAX_PHYSICAL_INTERFACES)
		return -ENODEV;
	if (!nss_vlan_prepare_if(n->ifnum, n))
		return -EIO;
	n->handler = true;
	if (nss_vlan_tx_set_mac_addr_msg(n->ifnum, n->mac) != NSS_TX_SUCCESS ||
	    nss_vlan_tx_set_mtu_msg(n->ifnum, n->mtu) != NSS_TX_SUCCESS ||
	    nss_vlan_tx_add_tag_msg(n->ifnum, ((u32)ETH_P_8021Q << 16) | n->vid,
				  n->phys_if, n->phys_if) != NSS_TX_SUCCESS)
		return -EIO;
	nss_vlan_publish_if(n->ifnum, NULL, n->dev, 0, n);
	n->published = true;
	ret = nss_bridge_mgr_offload_port_join(n->dev);
	if (ret)
		return ret;
	spin_lock_bh(&table_lock);
	n->phase = DSA_NSS_READY;
	spin_unlock_bh(&table_lock);
	return 0;
}

static int node_destroy(struct dsa_nss_node *n)
{
	int ret;

	if (n->ifnum < 0)
		return 0;
	spin_lock_bh(&table_lock);
	n->phase = DSA_NSS_REVOKING;
	spin_unlock_bh(&table_lock);
	if (n->published) {
		ret = nss_bridge_mgr_offload_port_revoke(n->dev, n->ifnum);
		if (ret)
			goto unknown;
		nss_vlan_withdraw_if(n->ifnum);
		n->published = false;
		synchronize_net();
	}
	if (n->handler) {
		nss_unregister_vlan_if(n->ifnum);
		n->handler = false;
	}
	if (nss_dynamic_interface_dealloc_node(n->ifnum,
		NSS_DYNAMIC_INTERFACE_TYPE_VLAN) != NSS_TX_SUCCESS) {
		ret = -EIO;
		goto unknown;
	}
	dev_put(n->dev);
	memset(n, 0, sizeof(*n));
	n->ifnum = -1;
	return 0;
unknown:
	n->phase = DSA_NSS_UNKNOWN;
	return ret;
}

static int disable_locked(void)
{
	int i, ret, error = 0;

	WRITE_ONCE(ready, false);
	if (!owner_has_resources()) {
		owner_unpin_if_empty();
		return 0;
	}
	ret = rules_pause_and_drain();
	if (ret)
		return ret;
	for (i = 0; i < DSA_NSS_MAX_NODES; i++) {
		ret = node_destroy(&nodes[i]);
		if (ret && !error)
			error = ret;
	}
	if (error)
		return error;
	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++) {
		if (!conduits[i].held)
			continue;
		ret = nss_data_plane_detach(conduits[i].dev);
		if (ret)
			return ret;
		dev_put(conduits[i].dev);
		memset(&conduits[i], 0, sizeof(conduits[i]));
	}
	if (allocation_uncertain)
		return -EUCLEAN;
	rules_resume();
	owner_unpin_if_empty();
	return 0;
}

static bool topology_matches(struct dsa_nss_want *want, int count)
{
	int i;

	if (!ready)
		return false;
	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++)
		if (conduits[i].held &&
		    nss_data_plane_state(conduits[i].dev) != NSS_DATA_PLANE_READY)
			return false;
	for (i = 0; i < count; i++) {
		struct dsa_nss_node *n = &nodes[i];

		if (n->phase != DSA_NSS_READY || n->dev != want[i].dev ||
		    n->vid != want[i].vid || n->mtu != want[i].dev->mtu ||
		    !ether_addr_equal(n->mac, want[i].dev->dev_addr) ||
		    n->phys_if != nss_cmn_get_interface_number_by_dev(want[i].conduit))
			return false;
	}
	for (; i < DSA_NSS_MAX_NODES; i++)
		if (nodes[i].ifnum >= 0)
			return false;
	return true;
}

static int enable_locked(void)
{
	struct dsa_nss_want want[DSA_NSS_MAX_NODES];
	int count, i, ret;

	if (allocation_uncertain)
		return -EUCLEAN;
	count = collect(want);
	if (count <= 0) {
		ret = disable_locked();
		return ret ? ret : (count ? count : -EAGAIN);
	}
	if (topology_matches(want, count))
		return rules_provider_hold();
	ret = disable_locked();
	if (ret)
		return ret;
	ret = rules_pause_and_drain();
	if (ret)
		return ret;
	for (i = 0; i < count; i++) {
		ret = conduit_attach(want[i].conduit);
		if (ret)
			goto fail;
	}
	for (i = 0; i < count; i++) {
		ret = node_create(&nodes[i], &want[i]);
		if (ret)
			goto fail;
	}
	WRITE_ONCE(ready, true);
	rules_resume();
	pr_info("qca-dsa-nss: physical conduits and %d VLAN nodes ready\n", count);
	return 0;
fail:
	last_error = ret;
	/* Preserve failed teardown ownership. A failed disable remains pinned. */
	if (disable_locked())
		pr_err("qca-dsa-nss: ownership unresolved; recovery requires reboot\n");
	return ret;
}

int qca_dsa_nss_if_num(struct net_device *conduit, u16 vid)
{
	int i, result = -1, phys_if;

	if (!READ_ONCE(ready) || !READ_ONCE(pause_fn) ||
	    !nss_data_plane_is_ready(conduit))
		return -1;
	phys_if = nss_cmn_get_interface_number_by_dev(conduit);
	spin_lock_bh(&table_lock);
	for (i = 0; i < DSA_NSS_MAX_NODES; i++)
		if (nodes[i].phase == DSA_NSS_READY && nodes[i].vid == vid &&
		    nodes[i].phys_if == phys_if) {
			result = nodes[i].ifnum;
			break;
		}
	spin_unlock_bh(&table_lock);
	return result;
}
EXPORT_SYMBOL_GPL(qca_dsa_nss_if_num);

/* ECM announces successful init. Until the worker acquires its live module
 * references, the hierarchy gate above refuses every wired CREATE.
 */
void qca_dsa_nss_ecm_notify(void)
{
	if (READ_ONCE(initialised) && !READ_ONCE(stopping))
		mod_delayed_work(system_wq, &reconcile_work, HZ);
}
EXPORT_SYMBOL_GPL(qca_dsa_nss_ecm_notify);

static void reconcile(struct work_struct *work)
{
	rtnl_lock();
	mutex_lock(&owner_lock);
	if (!stopping)
		last_error = enabled ? enable_locked() : disable_locked();
	mutex_unlock(&owner_lock);
	rtnl_unlock();
}

static int enabled_set(const char *value, const struct kernel_param *kp)
{
	bool requested;
	int ret;

	ret = kstrtobool(value, &requested);
	if (ret)
		return ret;
	if (!initialised) {
		enabled = requested;
		return 0;
	}
	cancel_delayed_work_sync(&reconcile_work);
	rtnl_lock();
	mutex_lock(&owner_lock);
	ret = requested ? enable_locked() : disable_locked();
	last_error = ret;
	if (!ret)
		enabled = requested;
	mutex_unlock(&owner_lock);
	rtnl_unlock();
	return ret;
}
static const struct kernel_param_ops enabled_ops = {
	.set = enabled_set, .get = param_get_bool,
};
module_param_cb(enabled, &enabled_ops, &enabled, 0600);
module_param_named(ready, ready, bool, 0444);

static int netdev_event(struct notifier_block *nb, unsigned long event, void *ptr)
{
	struct net_device *dev = netdev_notifier_info_to_dev(ptr);
	bool relevant = port_of(dev) || netif_is_bridge_master(dev);
	int i, ret = 0;

	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++)
		if (conduits[i].held && conduits[i].dev == dev)
			relevant = true;

	if (!relevant || !initialised || stopping)
		return NOTIFY_DONE;
	switch (event) {
	case NETDEV_PRECHANGEUPPER:
	case NETDEV_PRECHANGEMTU:
	case NETDEV_PRE_CHANGEADDR:
	case NETDEV_GOING_DOWN:
		/* Revoke while old tag/bridge identity is still valid. */
		if (ready || owner_has_resources()) {
			mutex_lock(&owner_lock);
			ret = disable_locked();
			last_error = ret;
			mutex_unlock(&owner_lock);
		}
		return notifier_from_errno(ret);
	case NETDEV_REGISTER:
	case NETDEV_UP:
	case NETDEV_CHANGE:
	case NETDEV_CHANGEUPPER:
	case NETDEV_CHANGEADDR:
	case NETDEV_CHANGEMTU:
	case NETDEV_CHANGEINFODATA:
	case NETDEV_DOWN:
		mod_delayed_work(system_wq, &reconcile_work, HZ);
		break;
	case NETDEV_UNREGISTER:
		mutex_lock(&owner_lock);
		last_error = disable_locked();
		mutex_unlock(&owner_lock);
		break;
	}
	return NOTIFY_DONE;
}
static struct notifier_block netdev_nb = {
	.notifier_call = netdev_event, .priority = 100,
};

static int status_show(struct seq_file *m, void *v)
{
	int i;

	rtnl_lock();
	mutex_lock(&owner_lock);
	seq_printf(m, "enabled=%d ready=%d pinned=%d paused=%d provider_held=%d allocation_uncertain=%d error=%d\n",
		enabled, ready, pinned, paused, !!pause_fn, allocation_uncertain, last_error);
	for (i = 0; i < DSA_NSS_MAX_CONDUITS; i++)
		if (conduits[i].held)
			seq_printf(m, "conduit=%s state=%d\n", conduits[i].dev->name,
				nss_data_plane_state(conduits[i].dev));
	for (i = 0; i < DSA_NSS_MAX_NODES; i++)
		if (nodes[i].ifnum >= 0)
			seq_printf(m, "node=%s ifnum=%d vid=%u phys=%d phase=%d published=%d handler=%d\n",
				nodes[i].dev->name, nodes[i].ifnum, nodes[i].vid,
				nodes[i].phys_if, nodes[i].phase, nodes[i].published, nodes[i].handler);
	mutex_unlock(&owner_lock);
	rtnl_unlock();
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(status);

static int __init dsa_nss_init(void)
{
	int i, ret;

	for (i = 0; i < DSA_NSS_MAX_NODES; i++)
		nodes[i].ifnum = -1;
	INIT_DELAYED_WORK(&reconcile_work, reconcile);
	ret = register_netdevice_notifier(&netdev_nb);
	if (ret)
		return ret;
	dentry = debugfs_create_dir("qca-dsa-nss", NULL);
	debugfs_create_file("status", 0444, dentry, NULL, &status_fops);
	initialised = true;
	if (enabled)
		schedule_delayed_work(&reconcile_work, HZ);
	return 0;
}

static void __exit dsa_nss_exit(void)
{
	/* Active and uncertain resources hold THIS_MODULE, so normal unload
 * reaches here only after explicit successful disable.
 */
	stopping = true;
	unregister_netdevice_notifier(&netdev_nb);
	cancel_delayed_work_sync(&reconcile_work);
	debugfs_remove_recursive(dentry);
}
module_init(dsa_nss_init);
module_exit(dsa_nss_exit);
MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("Verified NSS physical and VLAN ownership for QCA DSA");
