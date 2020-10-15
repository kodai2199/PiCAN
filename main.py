#!/usr/bin/env python3
from multiprocessing import Process, Queue
import logging
from datetime import datetime
from pathlib import Path
from processes.canprocess import CanProcess
from processes.socketprocess import socket_interface_process
from sim import Sim
from picandb.settingsmanager import SettingsManager


def main():
    # Two separate queues will allow IPC
    # The can_interface_process will put on can_to_socket_queue
    # results and information. It will get from socket_to_can_queue
    # commands to be executed.
    # The socket_interface_process will put on socket_to_can_queue
    # commands received from the socket. It will read from
    # can_to_socket_queue the results and the information and
    # send them to the server via the socket
    # TODO: test CAN functionality (special equipment needed!)
    # TODO: implement backup database functionality
    # WARNING: database exceptions are not catched, as there should be none!

    # Prepare the logger
    now = datetime.now()
    directory = Path("logs/")
    filename = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename += "_piCANcontroller.log"
    filename = directory / filename
    logging.basicConfig(level=logging.DEBUG, filename=filename, format="[%(asctime)s][%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)
    logger.debug("Logger ready")

    # Prepare the database
    logger.debug("Checking database state")
    settings = SettingsManager("piCANclient.db")
    old_imei = settings.get_setting("IMEI_impianto")

    logger.debug("Preparing GSM modem")
    sim = Sim()
    if sim.connected.is_set():
        sim.disconnect()
    new_imei = sim.get_imei()
    sim.connect()

    # If the old imei is the default, then replace it.
    # If the old imei is not the default and the new is different,
    # the modem has been replaced, so an exception is raised
    if old_imei == settings.DEFAULT_IMEI:
        settings.update_setting("IMEI_impianto", new_imei)
    elif new_imei != old_imei:
        settings.update_setting("IMEI_impianto_OK", 0)
        logger.error("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
        raise IOError("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
    settings.update_setting("IMEI_impianto_OK", 1)
    imei = new_imei

    can_to_socket_queue = Queue()
    socket_to_can_queue = Queue()
    can_process = CanProcess(socket_to_can_queue, can_to_socket_queue)
    socket_process = Process(target=socket_interface_process,
                             args=(can_to_socket_queue, socket_to_can_queue, imei, sim))

    can_process.start()
    socket_process.start()

    # Nothing else needs to be done
    socket_process.join()
    can_process.join()


if __name__ == "__main__":
    main()
