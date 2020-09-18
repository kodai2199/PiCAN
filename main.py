#!/usr/bin/env python3
import time
from multiprocessing import Process, Queue
import socket as sk
import json
import logging
from queue import Empty
from time import perf_counter, sleep
from datetime import datetime
from pathlib import Path
from sim import Sim
from picandb.settingsmanager import SettingsManager

SERVER_ADDRESS = "127.0.0.1"
PORT = 37863    # Port number decided arbitrarely


def send(socket, message):
    data = message.encode()
    try:
        print("Sending {}".format(message))
        socket.send(data)
    except ConnectionError:
        logging.error("Could not send data to the server")
        return False
    return True


def receive(socket):
    data = socket.recv(1024)
    message = data.decode("UTF-8")
    if not data or data is None:
        print("There was a problem receiving data from the server")
        raise ConnectionError("There was a problem receiving data from the server")
    return message


def get_info():
    """
    Load the last batch of information
    :return:
    """
    settings = SettingsManager("piCANclient.db")
    last_row = settings.get_last_data_row()
    if last_row is None:
        return "NO_DATA"
    else:
        return last_row


def time_increase(seconds, minutes, hours):
    seconds += 1
    if seconds == 60:
        minutes += 1
        seconds = 0
    if minutes == 60:
        hours += 1
        minutes = 0
    return seconds, minutes, hours


def time_updater():
    # This process will take care of updating the many time
    # variables in the database. Since database access time
    # may be significant, and an high-precision clock is needed
    # in order to avoid time drifts, perf_counter() will be used
    # sleep() will be considered "not precise"
    settings = SettingsManager("piCANclient.db")
    start_time = perf_counter()
    while True:
        rb_hour = settings.get_setting("impianto_RB_Counter_hour")
        rb_min = settings.get_setting("impianto_RB_Counter_min")
        rb_seconds = settings.get_setting("impianto_RB_Counter_sec")
        rb_seconds, rb_min, rb_hour = time_increase(int(rb_seconds), int(rb_min), int(rb_hour))

        bk_hour = settings.get_setting("impianto_BK_Counter_hour")
        bk_min = settings.get_setting("impianto_BK_Counter_min")
        bk_seconds = settings.get_setting("impianto_BK_Counter_sec")
        bk_seconds, bk_min, bk_hour = time_increase(int(bk_seconds), int(bk_min), int(bk_hour))

        tl_hour = settings.get_setting("impianto_TL_Counter_hour")
        tl_min = settings.get_setting("impianto_TL_Counter_min")
        tl_seconds = settings.get_setting("impianto_TL_Counter_sec")
        tl_seconds, tl_min, tl_hour = time_increase(int(tl_seconds), int(tl_min), int(tl_hour))

        settings.update_setting("impianto_RB_Counter_hour", str(rb_hour))
        settings.update_setting("impianto_RB_Counter_min", str(rb_min))
        settings.update_setting("impianto_RB_Counter_sec", str(rb_seconds))

        settings.update_setting("impianto_BK_Counter_hour", str(bk_hour))
        settings.update_setting("impianto_BK_Counter_min", str(bk_min))
        settings.update_setting("impianto_BK_Counter_sec", str(bk_seconds))

        settings.update_setting("impianto_TL_Counter_hour", str(tl_hour))
        settings.update_setting("impianto_TL_Counter_min", str(tl_min))
        settings.update_setting("impianto_TL_Counter_sec", str(tl_seconds))

        # Higher precision delay implementation
        end_time = perf_counter()
        remaining_time = 1-(end_time-start_time)
        sleep(remaining_time)
        start_time = perf_counter()


def can_interface_process(read_queue, write_queue):
    # Send or read from can when needed...
    while True:
        try:
            # Phase a) check for commands
            command = read_queue.get(timeout=1)
            logging.info("Executing {}".format(command))
            # TODO: Implement actual command sending
            result = "OK"
            write_queue.put(result)
        except Empty:
            # TODO: catch queue empty exception
            # Phase b) execute control tasks and update data
            pass
    pass


def socket_interface_process(read_queue, write_queue, imei):
    """
    This function is meant to be run as a concurrent process, like the
    can_interface_process. It connects with the webserver and handles
    the connection. It receives commands from the webserver, executes
    and replies to them.

    :param read_queue: queue to be shared with can_interface_process,
     from where this socket_interface process will get the data
     read from the CANbus connected at can_interface_process
    :param write_queue: queue to be shared with can_interface_process,
     where this socket_interface_process will write the commands
     received from the web-server
    :param imei: The IMEI that will be sent to the server for first
                identification
    :return:
    """
    last_row = None
    # REMEMBER THE SERVER WILL SEND ONLY A COMMAND AT A TIME
    while True:
        # Wait until data has been fed into the database
        while get_info() == "NO_DATA":
            time.sleep(1)
        with sk.socket(sk.AF_INET, sk.SOCK_STREAM) as s:
            try:
                # Implementing server handshake protocol
                s.connect((SERVER_ADDRESS, PORT))
                while True:
                    # Receive, execute, reply
                    message = receive(s)
                    if message == "ID_SUPPLICANT":
                        # The server is asking for identification
                        # Reply with IMEI
                        send(s, imei)
                    else:
                        logging.error("The server did not ask for identification")
                        raise ConnectionRefusedError("The server did not ask for identification")

                    while True:
                        # Identification successful
                        command = receive(s)
                        if command == "GET_INFO":
                            new_row = get_info()
                            if last_row == new_row:
                                # answer = "NO_UPDATE" let's save data
                                answer = "NU"
                            else:
                                last_row = new_row
                                answer = json.dumps(new_row)
                            send(s, answer)

            except ConnectionError or ConnectionResetError:
                logging.error("The connection has been closed unexpectedly. Trying to reconnect...")
                print("The connection has been closed unexpectedly. Trying to reconnect...")


def main():
    # Two separate queues will allow IPC
    # The can_interface_process will put on can_to_socket_queue
    # results and information. It will get from socket_to_can_queue
    # commands to be executed.
    # The socket_interface_process will put on socket_to_can_queue
    # commands received from the socket. It will read from
    # can_to_socket_queue the results and the information and
    # send them to the server via the socket
    # TODO: implement GSM
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
    logging.debug("Logger ready")

    # Prepare the database
    logging.debug("Checking database state")
    settings = SettingsManager("piCANclient.db")
    old_imei = settings.get_setting("IMEI_impianto")

    logging.debug("Preparing GSM modem")
    sim = Sim()
    new_imei = sim.get_imei()

    # If the old imei is the default, then replace it.
    # If the old imei is not the default and the new is different,
    # the modem has been replaced, so an exception is raised
    if old_imei == settings.DEFAULT_IMEI:
        settings.update_setting("IMEI_impianto", new_imei)
    elif new_imei != old_imei:
        logging.error("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
        raise IOError("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
    imei = new_imei

    can_to_socket_queue = Queue()
    socket_to_can_queue = Queue()
    can_process = Process(target=can_interface_process, args=(socket_to_can_queue, can_to_socket_queue))
    socket_process = Process(target=socket_interface_process, args=(can_to_socket_queue, socket_to_can_queue, imei))
    time_updater_process = Process(target=time_updater)
    time_updater_process.daemon = True

    # can_process.start()
    socket_process.start()
    # time_updater.start()

    # Nothing else needs to be done
    socket_process.join()
    # can_process.join()
    # time_updater is a daemon and will terminate with the program


if __name__ == "__main__":
    main()
