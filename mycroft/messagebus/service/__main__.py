import sys
import portalocker
from tornado import autoreload, web, ioloop

from mycroft.messagebus.load_config import load_message_bus_config
from mycroft.messagebus.service.event_handler import MessageBusEventHandler
from mycroft.util import (
    reset_sigint_handler,
    create_daemon,
    wait_for_exit_signal
)
from mycroft.util.log import LOG

LOCK_FILE = 'mycroft_messagebus_service.lock'

def on_ready():
    LOG.info('Message bus service started!')

def on_error(e='Unknown'):
    LOG.info('Message bus failed to start ({})'.format(repr(e)))

def on_stopping():
    LOG.info('Message bus is shutting down...')

def acquire_lock():
    """Acquire a lock using portalocker to ensure single instance."""
    lock_file = open(LOCK_FILE, 'a')
    try:
        portalocker.lock(lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
        return lock_file
    except portalocker.exceptions.LockException:
        lock_file.close()
        raise

def release_lock(lock_file):
    """Release the lock acquired by portalocker."""
    try:
        portalocker.unlock(lock_file)
        lock_file.close()
    except Exception as e:
        LOG.error("Failed to release lock: {}".format(e))

def main(ready_hook=on_ready, error_hook=on_error, stopping_hook=on_stopping):
    import tornado.options
    LOG.info('Starting message bus service...')
    reset_sigint_handler()

    try:
        lock_file = acquire_lock()
        LOG.info("Lock acquired successfully")
    except Exception as e:
        error_hook("Failed to acquire lock: {}".format(e))
        return

    # Disable all tornado logging so mycroft loglevel isn't overridden
    tornado.options.parse_command_line(sys.argv + ['--logging=None'])

    def reload_hook():
        """Hook to release lock when auto reload is triggered."""
        LOG.info("Releasing lock for autoreload")
        release_lock(lock_file)

    autoreload.add_reload_hook(reload_hook)
    
    try:
        config = load_message_bus_config()
        routes = [(config.route, MessageBusEventHandler)]
        application = web.Application(routes, debug=True)
        application.listen(config.port, config.host)
        create_daemon(ioloop.IOLoop.instance().start)
        ready_hook()
        wait_for_exit_signal()
    except Exception as e:
        error_hook(e)
    finally:
        stopping_hook()
        release_lock(lock_file)

if __name__ == "__main__":
    main()
