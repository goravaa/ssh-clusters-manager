import subprocess
import json
import time
import logging
import os
from ssh_cluster.types import HostInfo
from ssh_cluster.cluster import SSHCluster
from ssh_cluster.connection import SSHConnection
import platform

# ---- Configure logging ----
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("vast_test")

def run_cli(cmd):
    logger.info(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    logger.info(f"stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        logger.warning(f"stderr: {result.stderr.strip()}")
    if result.returncode != 0:
        logger.error(f"FAILED command: {cmd}")
        raise RuntimeError(result.stderr)
    return result.stdout

def vast_query_str(query: str) -> str:
    if platform.system() == "Windows":
        return f'"{query}"'
    else:
        return f"'{query}'"

def find_cheapest_offers(num):
    logger.info("Searching for cheapest offers on Vast...")
    quoted_query = vast_query_str("verified=True rentable=True")
    cmd = f"vastai search offers {quoted_query} --raw"
    out = run_cli(cmd)
    offers = json.loads(out)
    offers.sort(key=lambda o: float(o["dph_total"]))
    selected = offers[:num]
    logger.info(f"Selected offers: {[o['id'] for o in selected]}")
    return selected

def create_machine_from_offer(offer):
    logger.info(f"Creating instance for offer {offer['id']}")
    cmd = f"vastai create instance {offer['id']} --image pytorch/pytorch --disk 20 --ssh --raw"
    out = run_cli(cmd)
    data = json.loads(out)
    return data["new_contract"]

def wait_for_machines(ids):
    ready = set()
    logger.info("Waiting for all machines to be REALLY ready (status_msg contains 'success')...")
    for _ in range(60):  # up to 10 min (10s per loop)
        for i in ids:
            if i in ready:
                continue
            out = run_cli(f"vastai show instance {i} --raw")
            data = json.loads(out)
            status_msg = (data.get("status_msg") or "").lower()
            if "success" in status_msg:
                ready.add(i)
                logger.info(f"Machine {i} is REALLY ready! status_msg: {data.get('status_msg')}")
            else:
                logger.info(
                    f"Machine {i} NOT ready yet. cur_state={data.get('cur_state')} status_msg={data.get('status_msg')}"
                )
        if len(ready) == len(ids):
            break
        time.sleep(10)
    if len(ready) != len(ids):
        logger.error("Some machines did not become REALLY ready in time.")
        raise RuntimeError("Some machines did not become REALLY ready!")
    return list(ready)

def get_machine_info(ids, ssh_key_path: str):
    hosts = []
    logger.info("Gathering connection info for all machines...")
    for i in ids:
        out = run_cli(f"vastai show instance {i} --raw")
        data = json.loads(out)
        ssh_host = data.get("ssh_host")
        ssh_port = data.get("ssh_port")
        if not ssh_host or not ssh_port:
            logger.error(f"Machine {i} missing ssh_host or ssh_port! Full data: {data}")
            continue
        host = HostInfo(
            hostname=ssh_host,         # <- USE THE VAST JUMP HOST!
            port=ssh_port,
            username="root",
            key_filename=ssh_key_path,
            label=f"vast-{i}",
        )
        hosts.append(host)
        logger.info(f"Host {i}: {ssh_host}:{ssh_port} (root, key: {ssh_key_path})")
    return hosts



def main():
    # --- Ask user for their SSH key file path ---
    default_key = os.path.expanduser("~/.ssh/id_rsa")
    ssh_key_path = input(f"Enter path to your SSH private key (default: {default_key}): ").strip()
    if not ssh_key_path:
        ssh_key_path = default_key
    if not os.path.isfile(ssh_key_path):
        logger.error(f"SSH key file not found: {ssh_key_path}")
        return

    # 1. Find and create 5 cheapest machines
    offers = find_cheapest_offers(5)
    ids = []
    for offer in offers:
        try:
            id = create_machine_from_offer(offer)
            ids.append(id)
        except Exception as e:
            logger.error(f"Failed to create machine from offer {offer['id']}: {e}")
    ids = wait_for_machines(ids)
    hosts = get_machine_info(ids, ssh_key_path)

    # 2. Partition into clusters
    cluster1_hosts = hosts[:2]
    cluster2_hosts = hosts[2:]

    logger.info("Creating SSHCluster objects for clusters.")
    cluster1 = SSHCluster(cluster1_hosts)
    cluster2 = SSHCluster(cluster2_hosts)

    # 3. Upload a file to cluster1
    logger.info("Uploading test.txt to cluster1 (2 machines)...")
    r1 = cluster1.put("test.txt", "/tmp/test.txt")
    logger.info(f"Cluster1 put results: {r1}")

    # 4. Upload a directory to cluster2
    logger.info("Uploading myfolder/ to cluster2 (3 machines)...")
    r2 = cluster2.put_dir(r"C:\Users\garvw\Projects\ssh-clusters-manager\tests", "/tmp/myfolder")
    logger.info(f"Cluster2 put_dir results: {r2}")

    # 5. Single SSHConnection test on first host of cluster2
    logger.info("Single machine SSH ops (file, dir, command)...")
    single = SSHConnection(cluster2_hosts[0])
    res_file = single.put("test.txt", "/tmp/test.txt")
    logger.info(f"Single put: {res_file}")
    res_dir = single.put_dir(r"C:\Users\garvw\Projects\ssh-clusters-manager\tests", "/tmp/myfolder")
    logger.info(f"Single put_dir: {res_dir}")
    out = single.exec("echo hello && uname -a")
    logger.info(f"Single exec: {out.stdout}")
    single.close()

    logger.info("All tests complete.")

if __name__ == "__main__":
    main()
