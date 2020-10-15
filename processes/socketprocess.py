import json
import logging
import time
import socket as sk
import json
from multiprocessing import Process
from picandb.settingsmanager import SettingsManager
from processes.timeprocess import time_updater

SERVER_ADDRESS = "ggh.zapto.org"
PORT = 37863    # Port number decided arbitrarily

# TODO proper class conversion

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
    return last_row


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
    time_updater_reset = 0
    time_updater_process = Process(target=time_updater, args=(time_updater_reset,))
    time_updater_process.daemon = True
    time_updater_process.start()

    logger = logging.getLogger(__name__ + '.socket_process')
    settings = SettingsManager("piCANclient.db")
    last_row = {}
    # NOTE: The server will only send a command at a time.
    # NOTE: The server will wait for up to five seconds to execute the
    #       command.
    while True:
        # Check if data has been fed into the database. If yes load it
        data = get_info()
        if data is not None:
            settings.insert_new_data_row(data)
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
                        logger.error("The server did not ask for identification")
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
                        elif command == "RESET_TL":
                            time_updater_reset = 1
                            settings.update_setting("impianto_TL_Counter_hour", 0)
                            settings.update_setting("impianto_TL_Counter_min", 0)
                            settings.update_setting("impianto_TL_Counter_sec", 0)
                            settings.update_setting("impianto_TL_SERVICE", 0)
                            time_updater_reset = 0
                            send(s, "OK")
                        elif command == "RESET_BK":
                            time_updater_reset = 1
                            settings.update_setting("impianto_BK_Counter_hour", 0)
                            settings.update_setting("impianto_BK_Counter_min", 0)
                            settings.update_setting("impianto_BK_Counter_sec", 0)
                            settings.update_setting("impianto_BK_SERVICE", 0)
                            time_updater_reset = 0
                            send(s, "OK")
                        elif command == "RESET_RB":
                            time_updater_reset = 1
                            settings.update_setting("impianto_RB_Counter_hour", 0)
                            settings.update_setting("impianto_RB_Counter_min", 0)
                            settings.update_setting("impianto_RB_Counter_sec", 0)
                            settings.update_setting("impianto_RB_SERVICE", 0)
                            time_updater_reset = 0
                            send(s, "OK")
            except ConnectionError or ConnectionResetError:
                # If there was an issue connecting to the server, try to fix the issue until
                # it starts working again (cannot give up!)
                logger.error("The connection has been closed unexpectedly. Trying to reconnect...")
                print("The connection has been closed unexpectedly. Trying to reconnect...")
                # TODO call a method that pings google, if not works tries to disconnect and
                # TODO then reconnect with the modem. If ping works, then it must be server's fault
                time.sleep(1)
