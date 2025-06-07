from .cluster import SSHCluster
from .types import HostInfo
import logging

logger = logging.getLogger("sshmanager.manager")

class ClusterManager:
    """
    Manages multiple named SSHCluster objects.
    Allows adding/removing clusters and hosts, and running commands/files across clusters.
    """

    def __init__(self):
        self.clusters: dict[str, SSHCluster] = {}

    def create_cluster(self, name: str, hosts: list[HostInfo], **kwargs) -> SSHCluster:
        """
        Create or replace a named cluster.
        """
        if name in self.clusters:
            logger.warning(f"Cluster '{name}' already exists. Overwriting.")
        cluster = SSHCluster(hosts, **kwargs)
        self.clusters[name] = cluster
        logger.info(f"Created cluster '{name}' with {len(hosts)} hosts.")
        return cluster

    def add_host(self, cluster_name: str, host: HostInfo):
        """
        Add a host to an existing cluster.
        """
        if cluster_name not in self.clusters:
            logger.error(f"No such cluster '{cluster_name}' to add host.")
            raise ValueError(f"No such cluster '{cluster_name}'")
        cluster = self.clusters[cluster_name]
        cluster._hosts.append(host)
        cluster._connect_all()
        logger.info(f"Added host {host.hostname} to cluster '{cluster_name}'.")

    def remove_cluster(self, name: str):
        """
        Remove and close a cluster.
        """
        if name in self.clusters:
            self.clusters[name].close()
            del self.clusters[name]
            logger.info(f"Removed cluster '{name}'.")
        else:
            logger.warning(f"Tried to remove non-existent cluster '{name}'.")

    def list_clusters(self) -> list[str]:
        """
        List all cluster names.
        """
        return list(self.clusters.keys())

    def run_on_clusters(self, command: str, cluster_names=None, **kwargs):
        """
        Run a shell command on all hosts in each selected cluster.
        Returns: {cluster_name: {hostname: Result}}
        """
        results = {}
        targets = cluster_names or self.clusters.keys()
        for name in targets:
            cluster = self.clusters[name]
            logger.info(f"Running command '{command}' on cluster '{name}'")
            results[name] = cluster.run(command, **kwargs)
        return results

    def put_on_clusters(self, local: str, remote: str, cluster_names=None):
        """
        Upload a file to all hosts in each selected cluster.
        Returns: {cluster_name: {hostname: Result}}
        """
        results = {}
        targets = cluster_names or self.clusters.keys()
        for name in targets:
            cluster = self.clusters[name]
            logger.info(f"Uploading {local} to {remote} on cluster '{name}'")
            results[name] = cluster.put(local, remote)
        return results

    def get_on_clusters(self, remote: str, local: str, cluster_names=None):
        """
        Download a file from all hosts in each selected cluster.
        Returns: {cluster_name: {hostname: Result}}
        """
        results = {}
        targets = cluster_names or self.clusters.keys()
        for name in targets:
            cluster = self.clusters[name]
            logger.info(f"Downloading {remote} to {local} from cluster '{name}'")
            results[name] = cluster.get(remote, local)
        return results

    def close(self):
        """
        Close all clusters and their connections.
        """
        for cluster in self.clusters.values():
            cluster.close()
        logger.info("Closed all clusters.")

    def __getitem__(self, name: str) -> SSHCluster:
        return self.clusters[name]
