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
from cannetwork import CanNetwork
import random
from picandb.settingsmanager import SettingsManager

SERVER_ADDRESS = "ggh.zapto.org"
PORT = 37863    # Port number decided arbitrarily


def send(socket, message):
    """
    Encodes the message and sends it on the provided socket.

    :param socket: The connected socket to use
    :param message: The message to encode and send
    :return: True if message was successfully sent, False otherwise
    """
    data = message.encode()
    try:
        print("Sending {}".format(message))
        socket.send(data)
    except ConnectionError:
        logging.error("Could not send data to the server")
        return False
    return True


def receive(socket):
    """
    Listens for data on the provided socket and decodes it.

    :param socket: The connected socket from which to receive data
    :return: The decoded message
    """
    # TODO possible lock, implement with threaded timeout
    data = socket.recv(1024)
    message = data.decode("UTF-8")
    if not data or data is None:
        print("There was a problem receiving data from the server")
        raise ConnectionError("There was a problem receiving data from the server")
    return message


def get_info():
    """
    Returns the most up-to-date information available about the installation.

    If no information is stored in the database, then "NO_DATA" is returned.
    :return:
    """
    settings = SettingsManager("piCANclient.db")
    last_row = settings.get_last_data_row()
    if last_row is None:
        return "NO_DATA"
    else:
        return last_row


def time_increase(seconds, minutes, hours):
    """
    Takes hours, minutes and seconds and increases them by one second.
    :param seconds: the second
    :param minutes: the minute
    :param hours: the hour count (can be over 24)
    :return: the increased time as seconds, minutes and hours
    """
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
    run = int(settings.get_setting("Operator_Pump_start"))
    start_time = perf_counter()
    while True:
        if run == 1:
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

        run = int(settings.get_setting("Operator_Pump_start"))

        # Higher precision delay implementation
        end_time = perf_counter()
        remaining_time = 1-(end_time-start_time)
        sleep(remaining_time)
        start_time = perf_counter()


def randomly_generate_data():
    d = {}
    for field in SettingsManager.DATA_FIELDS:
        d[field] = random.randint(0, 1)
    return d


def can_interface_process(read_queue, write_queue):
    # TODO at process start all settings should be loaded and
    # TODO communicated via CAN Bus
    logger = logging.getLogger(__name__ + '.can_process')
    settings = SettingsManager("piCANclient.db")
    last_started = None
    anti_drip_start_count = 0
    anti_drip_start_count_limit = int(settings.get_setting("AntisgoccNpartenze"))
    anti_drip_min_period = int(settings.get_setting("AntisgoccDurataPartenze"))
    target_pressure = int(settings.get_setting("Pressione_Uscita_Target"))
    min_inlet_pressure = int(settings.get_setting("Pressione_Ingresso_Min"))
    max_inlet_pressure = int(settings.get_setting("Pressione_Ingresso_Max"))
    anti_drip_time_limit = int(settings.get_setting("AntisgoccPeriodoControllo"))
    if settings.get_setting("Antisgocc_OK") == 0:
        # If it's not ok then it's activated...
        anti_drip = True
    else:
        anti_drip = False
    operator_pump_start = settings.get_setting("Operator_Pump_start")
    anti_drip_current_time_frame = datetime.now()
    can_network = CanNetwork(autoconnect=True)
    can_network.initialize_nodes()
    while True:
        try:
            # Check for commands. Remember the .get() is blocking so the
            # process will wait until a command needs to be executed.
            command = read_queue.get(timeout=1)
            result = "INVALID"
            logging.info("Executing {}".format(command))
            # TODO: Implement actual command sending
            if command == "RUN":
                operator_pump_start = 1
                settings.update_setting("Operator_Pump_start", 1)
                can_network.run_all_nodes()
                result = "OK"
            elif command == "STOP":
                operator_pump_start = 0
                settings.update_setting("Operator_Pump_start", 0)
                can_network.stop_all_nodes()
                result = "OK"
            elif command == "GET_INFO":
                result = randomly_generate_data()
            print("EXECUTED {}".format(command))
            write_queue.put(result)
        except Empty:
            # Phase b). No commands were found. Then read data from
            # pressure sensors, read settings from the database and
            # execute

            # 1. If pumps have been running for more than anti_drip_time_limit
            #    then increase the anti_drip_start_count. If last started is None
            #    then it means that everything has already been calculated (or
            #    it has yet to start)
            if last_started is not None and (datetime.now() - last_started).total_seconds() >= anti_drip_min_period:
                anti_drip_start_count += 1
                last_started = None

            # 2. If the time window has expired, reset it. Otherwise, check the counter.
            #    If necessary, stop everything and set the anti_drip.
            if (datetime.now() - anti_drip_current_time_frame).total_seconds() > anti_drip_time_limit:
                anti_drip_current_time_frame = datetime.now()
                anti_drip_start_count = 0
            elif anti_drip_start_count == anti_drip_start_count_limit:
                settings.update_setting("Antisgocc_OK", 0)
                anti_drip = True

            # 3. Read pressure values and start or stop the pumps as necessary
            outlet_pressure = can_network.read_outlet_pressure()
            inlet_pressure = can_network.read_inlet_pressure()
            if outlet_pressure < inlet_pressure:
                logger.warning(f"Inlet pressure is {inlet_pressure}bar, which is higher than  the outlet pressure "
                               f" {outlet_pressure}bar. This is impossible. Check pressure sensor status.")
            if min_inlet_pressure < inlet_pressure < max_inlet_pressure:
                settings.update_setting("Pressione_Ingresso_OK", 1)
                if outlet_pressure < target_pressure and not anti_drip and operator_pump_start == 1:
                    # TODO Use inverter's PID
                    # could also smartly set speed...
                    can_network.run_all_nodes()
                    last_started = datetime.now()
                else:
                    can_network.stop_all_nodes()
            else:
                logger.warning(f"Inlet pressure of {inlet_pressure}bar, is outside limits. Pumps not started.")
            settings.update_setting("Pressione_Uscita", outlet_pressure)
            settings.update_setting("Pressione_Ingresso", inlet_pressure)


def socket_interface_process(read_queue, write_queue, imei, sim):
    """
    This function is meant to be run as a concurrent process, like the
    can_interface_process. It connects with the webserver and handles
    the connection. It receives commands from the webserver, executes
    via the can_interface_process and replies to them.

    Implemented commands:
        - "GET_INFO"
          The command is sent to the can_interface, which replies with
          the new data. Then only the changed data is sent to the
          server
        - "RUN"
          The command is sent to the can_interface, executed and then
          an "OK" is sent to the server.
        - "STOP"
          The command is sent to the can_interface, executed and then
          an "OK" is sent to the server.

    :param read_queue: queue to be shared with can_interface_process,
     from where this socket_interface process will get the data
     read from the CANbus connected at can_interface_process
    :param write_queue: queue to be shared with can_interface_process,
     where this socket_interface_process will write the commands
     received from the web-server
    :param imei: The IMEI that will be sent to the server for first
                identification
    :param sim: a reference to a Sim object to manage the connection,
                in case of a connection error.
    :return:
    """
    logger = logging.getLogger(__name__ + '.socket_process')
    settings = SettingsManager("piCANclient.db")
    last_row = None
    # NOTE: The server will only send a command at a time.
    # NOTE: The server will wait for up to five seconds to execute the
    #       command.
    while True:
        # Wait until data has been fed into the database
        while get_info() == "NO_DATA":
            data = randomly_generate_data()
            settings.insert_new_data_row(data)
            time.sleep(0.5)
        with sk.socket(sk.AF_INET, sk.SOCK_STREAM) as s:
            try:
                # Implementing server handshake protocol
                s.settimeout(None)
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
                            write_queue.put(command)
                            new_row = read_queue.get()
                            if last_row == new_row:
                                # answer = "NO_UPDATE" let's save data
                                answer = "NU"
                            else:
                                settings.insert_new_data_row(new_row)
                                # Only send the data that needs to be updated
                                to_update = {}
                                for key, value in new_row.items():
                                    if last_row is None or last_row[key] != value:
                                        to_update[key] = value
                                last_row = new_row
                                to_update["run"] = settings.get_setting("Operator_Pump_start")
                                answer = json.dumps(to_update)
                            send(s, answer)
                        elif command == "STOP":
                            write_queue.put(command)
                            result = read_queue.get()
                            if result == "OK":
                                send(s, "OK")
                            else:
                                print("ISSUE!")
                        elif command == "RUN":
                            write_queue.put(command)
                            result = read_queue.get()
                            if result == "OK":
                                send(s, "OK")
                            else:
                                print("ISSUE!")

            except ConnectionError or ConnectionResetError:
                # If there was an issue connecting to the server, try to fix the issue until
                # it starts working again (cannot give up!)
                logger.error("The connection has been closed unexpectedly. Trying to reconnect...")
                print("The connection has been closed unexpectedly. Trying to reconnect...")
                # TODO call a method that pings google, if not works tries to disconnect and
                # TODO then reconnect with the modem. If ping works, then it must be server's fault
                time.sleep(1)


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
    can_process = Process(target=can_interface_process,
                          args=(socket_to_can_queue, can_to_socket_queue))
    socket_process = Process(target=socket_interface_process,
                             args=(can_to_socket_queue, socket_to_can_queue, imei, sim))
    time_updater_process = Process(target=time_updater)
    time_updater_process.daemon = True

    can_process.start()
    socket_process.start()
    time_updater_process.start()

    # Nothing else needs to be done
    socket_process.join()
    can_process.join()
    # time_updater_process is a daemon and will terminate with the program


if __name__ == "__main__":
    main()
