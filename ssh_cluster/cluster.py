import paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed

class SSHCluster:
    def __init__(self, hosts):
        """
        Initialize the SSHCluster with a list of host configurations.
        Each host configuration should be a dictionary with:
          - hostname: (str) the host address.
          - port: (int, optional) SSH port (default 22).
          - username: (str) the SSH username.
          - password: (str, optional) password for authentication.
          - key_filename: (str, optional) path to an SSH private key.
        """
        self.hosts_info = hosts
        self.clients = {}  # Map hostname to a connected SSHClient instance.

    def connect_all(self):
        """
        Establish SSH connections for all configured hosts.
        """
        for host_info in self.hosts_info:
            hostname = host_info.get('hostname')
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname,
                    port=host_info.get('port', 22),
                    username=host_info.get('username'),
                    password=host_info.get('password'),
                    key_filename=host_info.get('key_filename')
                )
                self.clients[hostname] = client
                print(f"Connected to {hostname}")
            except Exception as e:
                print(f"Failed to connect to {hostname}: {e}")

    def disconnect_all(self):
        """
        Close all SSH connections.
        """
        for hostname, client in self.clients.items():
            client.close()
            print(f"Disconnected from {hostname}")
        self.clients = {}

    def _execute_command(self, hostname, client, command):
        """
        Helper method to execute a command on a single host.
        Returns a tuple of (output, error).
        """
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        return output, error

    def send_command(self, command, max_workers=5):
        """
        Send the given command concurrently to all connected hosts.
        This function waits (synchronously) until all responses are received.

        :param command: The shell command to execute.
        :param max_workers: Maximum threads to use concurrently.
        :return: Dictionary mapping hostname to a dict with 'output' and 'error'.
        """
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_host = {
                executor.submit(self._execute_command, hostname, client, command): hostname
                for hostname, client in self.clients.items()
            }
            for future in as_completed(future_to_host):
                hostname = future_to_host[future]
                try:
                    out, err = future.result()
                    results[hostname] = {'output': out, 'error': err}
                except Exception as e:
                    results[hostname] = {'output': '', 'error': str(e)}
        return results
