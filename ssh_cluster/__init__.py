import logging

logger = logging.getLogger("sshmanager")
logger.setLevel(logging.INFO)  # Default, override in user code

# You can also add a handler if none exists
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)
