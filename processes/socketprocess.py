import json
import logging
import time
import socket as sk
import json
from multiprocessing import Process
from threading import Thread
from picandb.settingsmanager import SettingsManager
from processes.timeprocess import time_updater

SERVER_ADDRESS = "ggh.zapto.org"
PORT = 37863


class SocketProcess(Process):

    def __init__(self, read_queue, write_queue, imei, sim, server_address='ggh.zapto.org', port=37863):
        super(SocketProcess, self).__init__()
        self.read_queue = read_queue
        self.write_queue = write_queue
        self.imei = imei
        self.sim = sim
        self.server_address = server_address
        self.port = port

        self.socket = None
        self.logger = logging.getLogger(__name__ + '.socket_process')
        self.time_updater_reset = 0
        self.time_updater_process = None
        self.settings = SettingsManager("piCANclient.db")

    def send(self, message: str):
        """
        Encodes the message and sends it on the object socket.

        :param message: The message to encode and send
        :return: True if message was successfully sent, False otherwise
        """
        data = message.encode()
        try:
            self.logger.info(f"Sending {message}")
            print(f"Sending {message}")
            self.socket.send(data)
        except ConnectionError:
            logging.error("Could not send data to the server")
            return False
        return True

    def receive_thread(self, buffer_size: int, data: list):
        # A simple wrapper for socket.recv to allow
        # thread execution and exception silencing
        try:
            data[0] = self.socket.recv(buffer_size)
        except ConnectionError or ConnectionAbortedError:
            pass

    def receive(self, timeout=0, buffer_size=1024) -> str:
        """
        Listens for data on the connection and decodes it. Optional
        parameters are timeout and buffer_size, which may be
        customized to make the function behave as necessary. In
        order to implement a reliable timeout for socket.recv, the
        call is wrapped in a thread. If it doesn't return before the
        timeout mark, then the thread is terminated by closing the
        connection and the function returns.

        :param timeout: Time in seconds to wait before closing the
                        connection if no data is sent. Timeout = 0
                        is default and means no timeout.
        :param buffer_size: The buffer size in bytes. Default is 1024
                            and should not be changed unless
                            necessary.
        :return:
        """
        data = [None]
        rec_thread = Thread(target=self.receive_thread, args=(buffer_size, data))
        rec_thread.daemon = True
        rec_thread.start()

        timer = 0
        if timeout > 0:
            while timer <= timeout:
                if not (data[0] is None):
                    break
                time.sleep(1)
                timer += 1
            if timer > timeout:
                self.socket.close()
                raise ConnectionAbortedError()
        else:
            rec_thread.join()

        data = data[0]
        if not data or data is None:
            self.logger.error(f"{self.server_address} closed the connection or did not send anything before timeout")
            raise ConnectionAbortedError()
        else:
            # Data should be an array of bytes!
            message = data.decode("UTF-8")
            print(f"{self.server_address} sent {message}")
            self.logger.info(f"{self.server_address} sent {message}")
            return message

    def receive_or_reconnect(self, timeout=0, buffer_size=1024):
        # USEFUL since sometimes 3G modem changes breaks the socket
        while True:
            try:
                return self.receive(timeout, buffer_size)
            except ConnectionAbortedError:
                self.create_socket()
                self.connect_to_server()

    def create_socket(self):
        self.socket = sk.socket(sk.AF_INET, sk.SOCK_STREAM)
        self.socket.settimeout(None)

    def connect_to_server(self):
        # REMEMBER TO CREATE SOCKET BEFORE CONNECTING
        try:
            self.socket.connect((self.server_address, self.port))
            self.identify()
        except ConnectionError or ConnectionResetError:
            self.logger.error("The connection has been closed unexpectedly. Trying to reconnect...")
            self.sim.disconnect(blocking=True)
            self.sim.connect(blocking=True)
            # Call a method that pings google, if not works tries to disconnect and
            # then reconnect with the modem. If ping works, then it must be server's fault
            # But what should we do, even if so? We could only wait and retry...

    def reset_time_limit(self, limit_name: str):
        self.time_updater_reset = 1
        self.settings.update_setting(f"impianto_{limit_name}_Counter_hour", 0)
        self.settings.update_setting(f"impianto_{limit_name}_Counter_min", 0)
        self.settings.update_setting(f"impianto_{limit_name}_Counter_sec", 0)
        self.settings.update_setting(f"impianto_{limit_name}_SERVICE", 0)
        self.time_updater_reset = 0

    def identify(self):
        # Identification
        message = self.receive_or_reconnect(10)
        if message == "ID_SUPPLICANT":
            self.send(self.imei)
        else:
            self.logger.error("The server did not ask for identification")
            raise ConnectionRefusedError("The server did not ask for identification")

    def run(self):
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
        self.time_updater_process = Process(target=time_updater, args=(self.time_updater_reset,))
        self.time_updater_process.daemon = True
        self.time_updater_process.start()
        last_row = {}
        # NOTE: The server will only send a command at a time.
        # NOTE: The server will wait for up to five seconds to execute the
        #       command.
        while True:
            self.create_socket()
            self.connect_to_server()
            while True:
                while True:
                    # Receive, execute, reply
                    command = self.receive_or_reconnect(10)
                    if command == "GET_INFO":
                        self.write_queue.put(command)
                        new_row = self.read_queue.get()
                        if "timestamp" in new_row:
                            del new_row["timestamp"]
                        if last_row == new_row:
                            # answer = "NO_UPDATE" let's save data
                            answer = "NU"
                        else:
                            self.settings.insert_new_data_row(new_row)
                            # Only send the data that needs to be updated
                            to_update = {}
                            for key, value in new_row.items():
                                if last_row is None or key not in last_row or last_row[key] != value:
                                    to_update[key] = value
                            last_row = new_row
                            answer = json.dumps(to_update)
                        self.send(answer)
                    elif command == "STOP":
                        self.write_queue.put(command)
                        result = self.read_queue.get()
                        if result == "OK":
                            self.send("OK")
                        else:
                            self.logger.error("ISSUE!")
                    elif command == "RUN":
                        self.write_queue.put(command)
                        result = self.read_queue.get()
                        if result == "OK":
                            self.send("OK")
                        else:
                            self.logger.error("ISSUE!")
                    elif command == "RESET_TL":
                        self.reset_time_limit("TL")
                        self.send("OK")
                    elif command == "RESET_BK":
                        self.reset_time_limit("BK")
                        self.send("OK")
                    elif command == "RESET_RB":
                        self.reset_time_limit("RB")
                        self.send("OK")
                    elif 'SET_PRESSURE_TARGET: ' in command:
                        pressure_target = command.split(' ')[1]
                        self.settings.update_setting("Pressione_Uscita_Target", pressure_target)
                        self.write_queue.put('RESET_PRESSURE_TARGET')
                        result = self.read_queue.get()
                        if result == "OK":
                            self.send(result)
                        else:
                            self.logger.error("ISSUE!")
            time.sleep(1)
